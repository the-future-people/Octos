"""
Staff profiles (15 Nov 2026): the ID card on the Staff page and each
person's My profile page.

Each person may ask to change their own phone, email or photo; the
request waits for the Branch Manager and takes effect only when he approves
it (16 Nov 2026). His own changes, and the changes he makes for his staff,
apply at once, and the person is told. Name, role, employee ID and branch
belong to the business: nobody changes them here. The email is also the
sign-in name, so an approved email change changes how that person signs in.

Photos live in the private bucket, like customer files, and are shown
through a link good for an hour. Every upload is turned the right way up,
cut down to 600px and saved as a JPEG, which also drops whatever the
camera wrote into it (location included).

The numbers are three per role, for today, this week (from Monday) or this
month, all counted from records Octos already keeps.
"""
import io
import re
import secrets
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

PERIODS = ('today', 'week', 'month')
PHOTO_MAX_BYTES = 8 * 1024 * 1024
PHOTO_SIDE = 600
PHOTO_LINK_SECONDS = 3600
PHONE = re.compile(r'^\+?[0-9 ]{9,20}$')
FIELD_WORDS = {'PHONE': 'phone number', 'EMAIL': 'email', 'PHOTO': 'photo'}

ROLE_LABELS = {
    'BRANCH_MANAGER': 'Branch Manager',
    'CASHIER': 'Cashier',
    'ATTENDANT': 'Attendant',
    'OPERATOR': 'Operator',
    'FLOW_COORDINATOR': 'Coordinator',
    'COORDINATOR': 'Coordinator',
}
COORDINATORS = ('FLOW_COORDINATOR', 'COORDINATOR')


class ProfileRefused(Exception):
    """A change that can't be made, with words fit to show the person."""


# ── The card ─────────────────────────────────────────────────────────────

def card(user, period='week', now=None):
    """Everything the ID card and the profile page show, for one person."""
    role = user.role.name if user.role_id else ''
    return {
        'id': user.pk,
        'full_name': user.full_name,
        'first_name': user.first_name,
        'initials': ''.join(w[0] for w in user.full_name.split()[:2]).upper() or '?',
        'role': role,
        'role_label': ROLE_LABELS.get(role) or (user.role.display_name if user.role_id else ''),
        'branch': user.branch.name if user.branch_id else '',
        'employee_id': user.employee_id,
        'email': user.email,
        'phone': user.phone,
        'joined': joined(user),
        'is_active': user.is_active,
        'photo_url': signed_url(user.photo),
        'approves_own': is_manager(user),
        'pending': [pending_row(c) for c in user.profile_changes.filter(status='PENDING')],
        'period': period,
        'numbers': numbers(user, period, now),
    }


def pending_row(change):
    return {
        'id': change.pk,
        'user_id': change.user_id,
        'field': change.field,
        'what': FIELD_WORDS[change.field],
        'value': change.new_value,
        'photo_url': signed_url(change.new_photo),
        'removes_photo': change.field == 'PHOTO' and not change.new_photo,
        'requested_at': change.created_at.isoformat(),
    }


def joined(user):
    """The day they started: the HR record's date, else when the account was approved or made."""
    from django.core.exceptions import ObjectDoesNotExist
    try:
        employee = user.employee_profile
    except ObjectDoesNotExist:
        employee = None
    if employee is not None and employee.date_joined:
        return employee.date_joined.isoformat()
    when = user.approved_at or user.created_at
    return timezone.localtime(when).date().isoformat() if when else None


def signed_url(file):
    """A link to a private image good for an hour, or None. On disk (development), the plain URL."""
    if not file:
        return None
    storage = file.storage
    connection = getattr(storage, 'connection', None)
    if connection is None:
        return file.url
    return connection.meta.client.generate_presigned_url(
        'get_object',
        Params={'Bucket': storage.bucket_name, 'Key': storage._normalize_name(file.name),
                'ResponseContentType': 'image/jpeg'},
        ExpiresIn=PHOTO_LINK_SECONDS,
    )


def photo_url(user):
    return signed_url(user.photo)


# ── Asking for a change (staff) ──────────────────────────────────────────

def is_manager(user):
    return bool(user.role_id and user.role.name == 'BRANCH_MANAGER')


def may_manage(manager, member):
    """A Branch Manager may change and approve photos, phones and emails for the people at his branch."""
    return bool(is_manager(manager) and manager.branch_id and member.branch_id == manager.branch_id)


def ask(user, field, value='', upload=None, remove=False):
    """
    A staff member's own change. The Branch Manager's applies at once; anyone
    else's waits for him. Returns the ProfileChange, or None when applied.
    """
    from apps.accounts.models import ProfileChange

    if field == 'PHONE':
        value = clean_phone(value)
    elif field == 'EMAIL':
        value = clean_email(value, user)
    photo = None if (field != 'PHOTO' or remove) else _prepared(upload)

    if is_manager(user):
        _apply(user, field, value, photo, remove)
        return None

    with transaction.atomic():
        for old in ProfileChange.objects.select_for_update().filter(user=user, field=field, status='PENDING'):
            old.status = ProfileChange.Status.REPLACED
            old.save(update_fields=['status', 'updated_at'])
            _drop(old)
        change = ProfileChange(user=user, field=field, new_value=value if field != 'PHOTO' else '')
        if photo is not None:
            change.new_photo.save(f'{user.pk}-{secrets.token_hex(4)}.jpg', ContentFile(photo), save=False)
        change.save()
    _tell_managers(change)
    return change


def withdraw(user, change_id):
    """Take back your own request while it is still waiting."""
    from apps.accounts.models import ProfileChange
    change = ProfileChange.objects.filter(pk=change_id, user=user, status='PENDING').first()
    if change is None:
        raise ProfileRefused('That request has already been decided.')
    change.status = ProfileChange.Status.REPLACED
    change.save(update_fields=['status', 'updated_at'])
    _drop(change)


# ── Deciding (the Branch Manager) ────────────────────────────────────────

def waiting_for(manager):
    """The requests at his branch waiting for him, oldest first."""
    from apps.accounts.models import ProfileChange
    if not (is_manager(manager) and manager.branch_id):
        return ProfileChange.objects.none()
    return (ProfileChange.objects.filter(status='PENDING', user__branch_id=manager.branch_id)
            .exclude(user=manager).select_related('user', 'user__role').order_by('created_at'))


def approve(manager, change_id):
    change = _decidable(manager, change_id)
    user = change.user
    value = change.new_value
    if change.field == 'EMAIL':
        value = clean_email(value, user)     # someone may have taken it since
    photo = None
    if change.new_photo:
        with change.new_photo.open('rb') as f:
            photo = f.read()
    _apply(user, change.field, value, photo, remove=change.field == 'PHOTO' and photo is None)
    _decide(change, manager, 'APPROVED')
    _drop(change)
    _notify(user, manager, f'{manager.full_name} approved your new {change.get_field_display().lower()}.'
            + (' Sign in with it from now on.' if change.field == 'EMAIL' else ''))
    return change


def reject(manager, change_id, note=''):
    change = _decidable(manager, change_id)
    note = (note or '').strip()[:300]
    change.note = note
    _decide(change, manager, 'REJECTED')
    _drop(change)
    _notify(change.user, manager, f"{manager.full_name} didn't approve your new {FIELD_WORDS[change.field]}"
            + (f': {note}' if note else '.'))
    return change


def _decidable(manager, change_id):
    change = waiting_for(manager).filter(pk=change_id).first()
    if change is None:
        raise ProfileRefused('That request is not waiting for you any more.')
    return change


def _decide(change, manager, status):
    change.status = status
    change.decided_by = manager
    change.decided_at = timezone.now()
    change.save(update_fields=['status', 'decided_by', 'decided_at', 'note', 'updated_at'])


# ── Applying ─────────────────────────────────────────────────────────────

def clean_phone(phone):
    phone = re.sub(r'[\s-]+', ' ', (phone or '').strip())
    if phone and not PHONE.match(phone):
        raise ProfileRefused('Enter a phone number of digits only, like 024 555 0172.')
    return phone


def clean_email(email, user):
    from django.core.exceptions import ValidationError
    from django.core.validators import validate_email
    from apps.accounts.models import CustomUser

    email = (email or '').strip().lower()
    try:
        validate_email(email)
    except ValidationError:
        raise ProfileRefused('Enter an email address like name@example.com.')
    if CustomUser.objects.filter(email__iexact=email).exclude(pk=user.pk).exists():
        raise ProfileRefused('Someone at Farhat already uses that email.')
    return email


def _apply(user, field, value, photo, remove=False):
    if field == 'PHONE':
        user.phone = value
        user.save(update_fields=['phone', 'updated_at'])
    elif field == 'EMAIL':
        user.email = value
        user.save(update_fields=['email', 'updated_at'])
    elif remove:
        _remove(user)
    else:
        _store(user, photo)


def set_phone(user, phone, by=None):
    """The Branch Manager changes it for someone (applies at once; they are told)."""
    _apply(user, 'PHONE', clean_phone(phone), None)
    _tell(user, by, 'your phone number')
    return user


def set_email(user, email, by=None):
    """The Branch Manager changes it for someone (applies at once; they are told, and sign in with it)."""
    _apply(user, 'EMAIL', clean_email(email, user), None)
    if by is not None and by.pk != user.pk:
        _notify(user, by, f'{by.full_name} changed your email to {user.email}. Sign in with it from now on.')
    return user


def set_photo(user, upload, by=None):
    """The Branch Manager changes it for someone (applies at once; they are told)."""
    _store(user, _prepared(upload))
    _tell(user, by, 'your photo')
    return user


def remove_photo(user, by=None):
    if user.photo:
        _remove(user)
        _tell(user, by, 'your photo', removed=True)
    return user


def _prepared(upload):
    """An upload as JPEG bytes: upright, at most 600px, with nothing else in it."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    if upload is None:
        raise ProfileRefused('Choose a photo first.')
    if upload.size > PHOTO_MAX_BYTES:
        raise ProfileRefused('That photo is too large. Use one under 8 MB.')
    try:
        image = Image.open(upload)
        image = ImageOps.exif_transpose(image)
    except (UnidentifiedImageError, OSError):
        raise ProfileRefused("That file isn't a photo Octos can read. Use a JPG or PNG.")
    image = image.convert('RGB')
    image.thumbnail((PHOTO_SIDE, PHOTO_SIDE))
    buffer = io.BytesIO()
    image.save(buffer, format='JPEG', quality=85)
    return buffer.getvalue()


def _store(user, jpeg):
    old = user.photo.name if user.photo else None
    user.photo.save(f'{user.pk}-{secrets.token_hex(4)}.jpg', ContentFile(jpeg), save=False)
    user.save(update_fields=['photo', 'updated_at'])
    _forget(user.photo.storage, old)


def _remove(user):
    storage, old = user.photo.storage, (user.photo.name if user.photo else None)
    user.photo = None
    user.save(update_fields=['photo', 'updated_at'])
    _forget(storage, old)


def _drop(change):
    """A decided or replaced request's waiting photo is deleted."""
    if change.new_photo:
        _forget(change.new_photo.storage, change.new_photo.name)


def _forget(storage, name):
    """Delete a file no longer needed. A failure here must not undo the change."""
    if not name:
        return
    try:
        storage.delete(name)
    except Exception:
        pass


# ── Telling people ───────────────────────────────────────────────────────

def _notify(recipient, actor, message, link=''):
    from apps.notifications.services import notify
    notify(recipient=recipient, verb='system', actor=actor, message=message, link=link)


def _tell(user, by, what, removed=False):
    """The person is told when the Branch Manager changes their profile; never about their own change."""
    if by is None or by.pk == user.pk:
        return
    _notify(user, by, f'{by.full_name} {"removed" if removed else "updated"} {what}.')


def _tell_managers(change):
    """The branch's Branch Manager is asked to approve, with a link to the Staff page."""
    from apps.accounts.models import CustomUser
    user = change.user
    if not user.branch_id:
        return
    for manager in CustomUser.objects.filter(branch_id=user.branch_id, is_active=True,
                                             role__name='BRANCH_MANAGER').exclude(pk=user.pk):
        if change.field == 'PHOTO':
            what = 'to remove their photo' if not change.new_photo else 'to change their photo'
        else:
            what = f'to change their {FIELD_WORDS[change.field]} to {change.new_value}'
        _notify(manager, user, f'{user.full_name} asked {what}. Approve it on the Staff page.', link='/bm/staff/')


# ── Numbers ──────────────────────────────────────────────────────────────

def period_start(period, now=None):
    now = timezone.localtime(now or timezone.now())
    day = now.date()
    if period == 'week':
        day -= timedelta(days=day.weekday())
    elif period == 'month':
        day = day.replace(day=1)
    return timezone.make_aware(datetime.combine(day, time.min))


def numbers(user, period='week', now=None):
    """Three [{'label', 'value'}] for this person's role, over the period."""
    start = period_start(period, now)
    role = user.role.name if user.role_id else ''
    if role == 'ATTENDANT':
        rows = _attendant(user, start)
    elif role == 'CASHIER':
        rows = _cashier(user, start)
    elif role == 'OPERATOR':
        rows = _operator(user, start)
    elif role in COORDINATORS:
        rows = _coordinator(user, start)
    elif role == 'BRANCH_MANAGER':
        rows = _manager(user, start)
    else:
        rows = [('Days on', str(_days_on(user, start))), ('Hours active', _hours(_active_seconds(user, start) / 60))]
    return [{'label': label, 'value': value} for label, value in rows]


def _attendant(user, start):
    from apps.finance.models import AttendantSignOff
    from apps.jobs.models import Job, JobStatusLog

    recorded = (Job.objects.filter(intake_by=user, created_at__gte=start, voided_at__isnull=True)
                .exclude(status=Job.DRAFT).count())
    desk_done = (JobStatusLog.objects
                 .filter(actor=user, axis=JobStatusLog.Axis.WORK, to_status='DONE',
                         transitioned_at__gte=start, job__front_desk=True)
                 .values('job_id').distinct().count())
    signoffs = AttendantSignOff.objects.filter(attendant=user, signed_off_at__gte=start)
    return [('Jobs recorded', str(recorded)),
            ('Front desk done', str(desk_done)),
            ('Signed off themselves', _of(signoffs.filter(is_auto=False).count(), signoffs.count()))]


def _cashier(user, start):
    from apps.finance.models import CashierFloat, Receipt
    from apps.finance.services.my_numbers import wait_to_pay

    receipts = Receipt.objects.filter(cashier=user, is_void=False, created_at__gte=start)
    shifts = list(CashierFloat.objects.filter(cashier=user, is_signed_off=True, signed_off_at__gte=start)
                  .values_list('variance', flat=True))
    exact = sum(1 for v in shifts if abs(Decimal(v or 0)) <= Decimal('0.01'))
    wait = wait_to_pay(list(receipts.filter(job__isnull=False).values_list('job__created_at', 'created_at')))
    return [('Receipts', str(receipts.count())),
            ('Drawer exact', _of(exact, len(shifts))),
            ('Avg wait to pay', f'{wait}m' if wait is not None else '—')]


def _operator(user, start):
    from apps.jobs.models import JobStep
    from apps.production.models import MachineOperator

    done = JobStep.objects.filter(done_by=user, done_at__gte=start)
    minutes = done.aggregate(total=Sum('expected_minutes'))['total'] or 0
    machines = MachineOperator.objects.filter(operator=user, active_until__isnull=True).count()
    return [('Steps done', str(done.count())),
            ('Machine work', _hours(float(minutes))),
            ('Machines', str(machines))]


def _coordinator(user, start):
    from apps.jobs.models import JobVerification

    checked = JobVerification.objects.filter(checked_by=user, checked_at__gte=start)
    return [('Jobs checked', str(checked.count())),
            ('Cleared', str(checked.filter(outcome=JobVerification.Outcome.PASSED).count())),
            ('Hours active', _hours(_active_seconds(user, start) / 60))]


def _manager(user, start):
    from apps.communications.models import Message
    from apps.jobs.models import Job

    chats = (Message.objects
             .filter(sent_by=user, direction=Message.OUTBOUND, is_internal_note=False, created_at__gte=start)
             .values('conversation_id').distinct().count())
    approvals = Job.objects.filter(
        Q(post_closing_approved_by=user, created_at__gte=start)
        | Q(handover_resolved_by=user, handover_resolved_at__gte=start)
    ).count()
    return [('Chats handled', str(chats)),
            ('Approvals', str(approvals)),
            ('Hours active', _hours(_active_seconds(user, start) / 60))]


def _active_seconds(user, start):
    from apps.analytics.models import UserSession
    return (UserSession.objects.filter(user=user, started_at__gte=start)
            .aggregate(total=Sum('active_duration_seconds'))['total'] or 0)


def _days_on(user, start):
    from apps.analytics.models import UserSession
    return len({timezone.localtime(t).date() for t in
                UserSession.objects.filter(user=user, last_seen_at__gte=start).values_list('last_seen_at', flat=True)})


def _of(part, whole):
    return f'{part}/{whole}' if whole else '—'


def _hours(minutes):
    minutes = int(round(minutes or 0))
    if minutes == 0:
        return '0h'
    h, m = divmod(minutes, 60)
    return f'{h}h {m}m' if h and m else (f'{h}h' if h else f'{m}m')
