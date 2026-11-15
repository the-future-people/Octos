"""
Staff profiles (15 Nov 2026): the ID card on the Staff page and each
person's My profile page.

Each person may change their own photo and phone. The Branch Manager may
change them for anyone at his branch, and the person is told. Name, role,
employee ID, email and branch belong to the business: nobody changes them
here.

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
from django.db.models import Q, Sum
from django.utils import timezone

PERIODS = ('today', 'week', 'month')
PHOTO_MAX_BYTES = 8 * 1024 * 1024
PHOTO_SIDE = 600
PHOTO_LINK_SECONDS = 3600
PHONE = re.compile(r'^\+?[0-9 ]{9,20}$')

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
        'photo_url': photo_url(user),
        'period': period,
        'numbers': numbers(user, period, now),
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


def photo_url(user):
    """A link to the photo good for an hour, or None. On disk (development), the plain URL."""
    if not user.photo:
        return None
    storage = user.photo.storage
    connection = getattr(storage, 'connection', None)
    if connection is None:
        return user.photo.url
    return connection.meta.client.generate_presigned_url(
        'get_object',
        Params={'Bucket': storage.bucket_name, 'Key': storage._normalize_name(user.photo.name),
                'ResponseContentType': 'image/jpeg'},
        ExpiresIn=PHOTO_LINK_SECONDS,
    )


# ── Changes ──────────────────────────────────────────────────────────────

def may_manage(manager, member):
    """A Branch Manager may change photos and phones for the people at his branch."""
    return (manager.role_id and manager.role.name == 'BRANCH_MANAGER'
            and manager.branch_id and member.branch_id == manager.branch_id)


def set_phone(user, phone, by=None):
    phone = re.sub(r'[\s-]+', ' ', (phone or '').strip())
    if phone and not PHONE.match(phone):
        raise ProfileRefused('Enter a phone number of digits only, like 024 555 0172.')
    user.phone = phone
    user.save(update_fields=['phone', 'updated_at'])
    _tell(user, by, 'your phone number')
    return user


def set_photo(user, upload, by=None):
    """Save an uploaded photo: upright, at most 600px, as a JPEG with nothing else in it."""
    from PIL import Image, ImageOps, UnidentifiedImageError

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

    old = user.photo.name if user.photo else None
    user.photo.save(f'{user.pk}-{secrets.token_hex(4)}.jpg', ContentFile(buffer.getvalue()), save=False)
    user.save(update_fields=['photo', 'updated_at'])
    _forget(user, old)
    _tell(user, by, 'your photo')
    return user


def remove_photo(user, by=None):
    old = user.photo.name if user.photo else None
    if not old:
        return user
    user.photo = None
    user.save(update_fields=['photo', 'updated_at'])
    _forget(user, old)
    _tell(user, by, 'your photo', removed=True)
    return user


def _forget(user, name):
    """Delete a replaced photo. A failure here must not undo the change."""
    if not name:
        return
    try:
        user.photo.storage.delete(name)
    except Exception:
        pass


def _tell(user, by, what, removed=False):
    """The person is told when the Branch Manager changes their profile; never about their own change."""
    if by is None or by.pk == user.pk:
        return
    from apps.notifications.services import notify
    verb = 'removed' if removed else 'updated'
    notify(recipient=user, verb='system', actor=by, message=f'{by.full_name} {verb} {what}.')


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
