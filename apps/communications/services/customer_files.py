"""
Customer files: kept 14 days, unless the customer asks us to keep them
(25 Nov 2026).

Every CV, results slip and ID card sent to Octos used to stay in storage
for ever. Now:

  14 days      every night Octos deletes customer files older than 14 days:
               chat files (theirs, and what staff sent them), files on jobs,
               files on online orders. Never a file still needed by an open
               job: it goes once the job is done.
  Keep         the customer asked us to save it ("keep my CV for next
               time"): staff press Keep, or Octos marks it. It stays until
               they ask us to delete it.
  On request   an attendant can delete a customer's files, with a reason.
               Never while a job of theirs is open (unpaid, or not collected):
               those files are what we print from and our proof of what was
               sent. Only the BM or the owner lifts that lock; an attendant
               asks the owner on his line.

Deleting never destroys the evidence that a file existed: the chat card
keeps its name, pages, size, a fingerprint (sha256) and who deleted it and
why, and a file.deleted event records every copy that went. Our own files
(receipts, proformas, Octos's previews) aren't customer files and stay.
"""
import hashlib
import logging
from datetime import date, timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

logger = logging.getLogger(__name__)

RETAIN = timedelta(days=14)
REASONS = {
    'asked':   'The customer asked',
    'mistake': 'Sent to us by mistake',
    'other':   'Something else',
}
OCTOS_REASON = 'Deleted by Octos after 14 days'
OUR_KINDS = ('receipt', 'proforma', 'preview', 'quote_pdf')


class FilesRefused(Exception):
    """Not allowed, in words the person can read."""


# ── Who ──────────────────────────────────────────────────────────────────────

def _role(user):
    from apps.core.finance_scope import get_role_name
    return get_role_name(user) if user is not None else ''


def may_delete(user):
    from apps.jobs.status_engine import ATTENDANT_ROLE, AXIS_OVERRIDE_ROLES
    return _role(user) in ({ATTENDANT_ROLE} | AXIS_OVERRIDE_ROLES)


def may_unlock(user):
    """The BM and above: may delete files a job still holds."""
    from apps.jobs.status_engine import AXIS_OVERRIDE_ROLES
    return _role(user) in AXIS_OVERRIDE_ROLES


# ── Which files ──────────────────────────────────────────────────────────────

def chat_files(conversation):
    """The customer files in a chat still in storage: theirs, and what staff sent them."""
    from apps.communications.models import Message
    return (Message.objects.filter(conversation=conversation, file_deleted_at__isnull=True)
            .exclude(media_file='').exclude(media_file__isnull=True)
            .filter(Q(direction=Message.INBOUND) | Q(sent_by__isnull=False))
            .exclude(kind__in=OUR_KINDS)
            .order_by('created_at'))


def _theirs(conversation):
    from apps.jobs.models import Job
    q = Q(conversations=conversation)
    if conversation.customer_id:
        q |= Q(customer_id=conversation.customer_id)
    return Job.objects.filter(q).distinct()


def _open(jobs):
    from apps.jobs.models import Job
    return (jobs.exclude(status__in=[Job.CANCELLED, Job.VOIDED, Job.DRAFT])
            .exclude(payment_state=Job.Payment.SETTLED, handover_state=Job.Handover.HANDED_OVER))


def open_job(conversation):
    """A job of theirs that still needs their files: not paid, or not collected. None when all are done."""
    return _open(_theirs(conversation)).order_by('created_at').first()


def lock_text(job):
    if job is None:
        return ''
    from apps.jobs.models import Job
    paid = job.payment_state == Job.Payment.SETTLED
    return f'On job {job.job_number}, ' + ('not collected yet' if paid else 'not paid yet')


def deletes_on(message):
    """The day the nightly clean-up takes it, or None when kept."""
    if message.kept_at or message.file_deleted_at:
        return None
    return timezone.localdate(message.created_at + RETAIN) + timedelta(days=1)


# ── Fingerprints and copies ──────────────────────────────────────────────────

def fingerprint(fieldfile):
    """sha256 of a stored file, read in chunks; '' when it can't be read."""
    if not fieldfile:
        return ''
    digest = hashlib.sha256()
    try:
        with fieldfile.open('rb') as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                digest.update(chunk)
    except Exception:
        logger.warning('Could not read %s for its fingerprint', getattr(fieldfile, 'name', ''), exc_info=True)
        return ''
    return digest.hexdigest()


def _message_print(message):
    if not message.file_sha256 and message.media_file:
        message.file_sha256 = fingerprint(message.media_file)
        if message.file_sha256:
            type(message).objects.filter(pk=message.pk).update(file_sha256=message.file_sha256)
    return message.file_sha256


def copies(conversation, sha):
    """The same file on their jobs and online orders: (job files, order files)."""
    from apps.jobs.models import JobFile
    from apps.storefront.models import OrderFile

    if not sha:
        return [], []
    job_files = [f for f in JobFile.objects.filter(job__in=_theirs(conversation)).exclude(file='')
                 if fingerprint(f.file) == sha]
    orders = Q(order__notes__contains=f'(conversation {conversation.pk})')
    if conversation.contact_phone:
        orders |= Q(order__lead__phone=conversation.contact_phone)
    order_files = [f for f in OrderFile.objects.filter(orders).exclude(file='') if fingerprint(f.file) == sha]
    return job_files, order_files


# ── Keep ─────────────────────────────────────────────────────────────────────

def keep(messages, user=None, keep_it=True):
    """Kept (or given back its 14 days). user None: Octos, at the customer's word. Returns how many changed."""
    from apps.communications.models import Message
    from apps.spine import kinds
    from apps.spine.models import Event
    from apps.spine.recorder import record

    now = timezone.now()
    changed = 0
    for message in messages:
        if message.file_deleted_at:
            continue
        if keep_it and not message.kept_at:
            Message.objects.filter(pk=message.pk).update(kept_at=now, kept_by=user)
            record(kinds.FILE_KEPT, actor=Event.STAFF if user else Event.OCTOS, actor_user=user,
                   conversation=message.conversation, customer=message.conversation.customer,
                   payload={'message': message.pk, 'name': message.media_name})
            changed += 1
        elif not keep_it and message.kept_at:
            Message.objects.filter(pk=message.pk).update(kept_at=None, kept_by=None)
            changed += 1
    return changed


def keep_chat(conversation):
    """Octos heard "please keep my files": every customer file in the chat, kept."""
    return keep(list(chat_files(conversation).filter(direction='INBOUND')), None)


# ── Delete ───────────────────────────────────────────────────────────────────

def _gone(fieldfile):
    try:
        fieldfile.delete(save=False)
    except Exception:
        logger.warning('Could not delete %s from storage', getattr(fieldfile, 'name', ''), exc_info=True)


def delete(conversation, messages, actor, reason, note='', *, unlocked_by=None):
    """
    Delete these chat files and every copy of them on the customer's jobs and
    orders. actor None: Octos (the 14-day clean-up). Refuses while a job of
    theirs is open, unless the actor (or unlocked_by, the owner from his
    line) may lift the lock. Returns the messages deleted.
    """
    from apps.communications.models import Message
    from apps.spine import kinds
    from apps.spine.models import Event
    from apps.spine.recorder import record

    if actor is not None and not may_delete(actor):
        raise FilesRefused('Only attendants and managers can delete customer files.')
    held = open_job(conversation)
    if held is not None and not (unlocked_by or (actor is not None and may_unlock(actor))):
        raise FilesRefused(f'Locked for now: {lock_text(held)}. The BM or Khofi can delete it.')
    words = REASONS.get(reason, reason or '') if actor is not None else OCTOS_REASON
    if note:
        words = f'{words}: {note}'[:200]
    if unlocked_by is not None:
        words = f'{words} (allowed by {unlocked_by})'[:200]

    now = timezone.now()
    done = []
    for message in messages:
        message.refresh_from_db()
        if message.file_deleted_at or not message.media_file:
            continue
        sha = _message_print(message)
        job_files, order_files = copies(conversation, sha)
        gone = [{'what': 'job file', 'job': f.job.job_number, 'name': f.file.name.rsplit('/', 1)[-1]} for f in job_files]
        gone += [{'what': 'order file', 'order': f.order.order_number, 'name': f.original_filename} for f in order_files]
        with transaction.atomic():
            for f in job_files:
                _gone(f.file)
                f.delete()
            for f in order_files:
                _gone(f.file)
                f.delete()
            _gone(message.media_file)
            Message.objects.filter(pk=message.pk).update(
                media_file='', file_deleted_at=now, file_deleted_by=actor, file_delete_reason=words,
                kept_at=None, kept_by=None)
            record(kinds.FILE_DELETED, actor=Event.STAFF if actor else Event.OCTOS, actor_user=actor,
                   conversation=conversation, customer=conversation.customer, reason=words,
                   payload={'message': message.pk, 'name': message.media_name, 'pages': message.media_pages,
                            'size': message.media_size, 'sha256': sha, 'copies': gone})
        done.append(message)
    if reason == 'asked':
        _never_fetch(conversation, now, actor, words)
    return done


def _never_fetch(conversation, now, actor, words):
    """
    Files of theirs we never managed to save are marked deleted too, so a
    later try can't bring one back after we told them their files are gone
    (27 Nov 2026: Lorrey's loan agreement failed to arrive, she asked for her
    files deleted, and fetching it again would have stored it).
    """
    from apps.communications.models import Message
    (Message.objects.filter(conversation=conversation, direction=Message.INBOUND, media_file='',
                            file_deleted_at__isnull=True, created_at__lte=now)
     .filter(Q(media_id__gt='') | Q(kind=Message.FROM_LINK))
     .update(file_deleted_at=now, file_deleted_by=actor, file_delete_reason=words))


def delete_by_hand(conversation, ids, actor, reason, note=''):
    """The inbox's Delete: the chosen files, then the owner and the customer are told."""
    messages = [m for m in chat_files(conversation) if m.pk in set(ids)]
    if not messages:
        raise FilesRefused('Those files are already gone.')
    done = delete(conversation, messages, actor, reason, note)
    if done:
        transaction.on_commit(lambda: _tell_owner(conversation, done, actor, reason, note))
        if reason == 'asked':
            transaction.on_commit(lambda: _tell_customer(conversation, done))
    return done


def _who(conversation):
    from apps.communications.services import names
    return names.name_for(conversation, conversation.customer) or conversation.contact_name or 'A customer'


def _tell_owner(conversation, done, actor, reason, note):
    try:
        from apps.communications.services import owner_line
        listed = '\n'.join(f'· {m.media_name or "a file"}' + (f' ({m.media_pages} page{"s" if m.media_pages != 1 else ""})'
                                                              if m.media_pages else '') for m in done)
        why = REASONS.get(reason, reason)
        phone = f' (…{conversation.contact_phone[-4:]})' if conversation.contact_phone else ''
        owner_line.tell(
            'files_deleted',
            f'*Files deleted*\n{actor.first_name or "Someone"} deleted {len(done)} file{"s" if len(done) != 1 else ""} '
            f'from {_who(conversation)}\'s chat{phone}:\n{listed}\nReason: {why.lower()}{": " + note if note else ""}.',
        )
    except Exception:
        logger.exception('Owner not told about deleted files in chat %s', conversation.pk)


def _tell_customer(conversation, done):
    try:
        from apps.communications.services.whatsapp_outbound import WindowClosed, send_text
        from apps.communications.services.window import window_open
        if not window_open(conversation):
            return
        send_text(conversation, "Done \U0001F60A We've deleted the files you sent us. "
                                "They're no longer stored with us.", kind='files_deleted')
    except (WindowClosed, ValueError):
        pass
    except Exception:
        logger.exception('Customer not told about deleted files in chat %s', conversation.pk)


# ── The lock, from the owner's line ──────────────────────────────────────────

def ask_owner(conversation, ids, actor, reason, note=''):
    """An attendant wants files a job still holds deleted: the owner decides on his line."""
    from apps.communications.services import owner_line

    if not may_delete(actor):
        raise FilesRefused('Only attendants and managers can delete customer files.')
    messages = [m for m in chat_files(conversation) if m.pk in set(ids)]
    held = open_job(conversation)
    if not messages or held is None:
        raise FilesRefused('Nothing is locked: delete them straight away.')
    code = reason if reason in REASONS else 'other'
    token = f'{conversation.pk}:{actor.pk}:{code}:' + '.'.join(str(m.pk) for m in messages)
    names = ', '.join(m.media_name or 'a file' for m in messages)
    why = REASONS[code] + (f': "{note}"' if note else '')
    return owner_line.tell(
        'files_unlock',
        f'*Delete files on an open job?*\n{actor.first_name or "An attendant"} wants to delete {names} '
        f'from {_who(conversation)}\'s chat. {lock_text(held)}.\nTheir reason: {why}.',
        buttons=[{'id': f'files:allow:{token}', 'title': 'Let them delete it'},
                 {'id': f'files:keep:{token}', 'title': 'Keep it'}],
        ref=f'files:{conversation.pk}',
    )


def tap(reply_id):
    """The owner answered: files:allow:<chat>:<user>:<reason>:<ids> or files:keep:…"""
    from apps.accounts.models import CustomUser
    from apps.communications.models import Conversation

    try:
        _, choice, chat, user, code, ids = reply_id.split(':', 5)
        conversation = Conversation.objects.get(pk=int(chat))
        actor = CustomUser.objects.get(pk=int(user))
        wanted = [int(i) for i in ids.split('.') if i]
    except Exception:
        logger.warning('Unreadable files tap %r', reply_id)
        return None
    if choice != 'allow':
        return None
    messages = [m for m in chat_files(conversation) if m.pk in set(wanted)]
    done = delete(conversation, messages, actor, code, unlocked_by='Khofi')
    if done and code == 'asked':
        transaction.on_commit(lambda: _tell_customer(conversation, done))
    return done


# ── Every night ──────────────────────────────────────────────────────────────

def starts():
    """The first night the clean-up runs (FILE_CLEANUP_STARTS): time to mark older files Keep first."""
    value = getattr(settings, 'FILE_CLEANUP_STARTS', '') or ''
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def clean(now=None):
    """
    Customer files older than 14 days, not kept, not held by an open job:
    chat files (and their copies), then job and order files on their own.
    Returns how many were deleted.
    """
    from apps.communications.models import Conversation, Message
    from apps.jobs.models import Job, JobFile
    from apps.spine import kinds
    from apps.spine.models import Event
    from apps.spine.recorder import record
    from apps.storefront.models import OrderFile

    now = now or timezone.now()
    first = starts()
    if first is None or timezone.localdate(now) < first:
        return 0
    cutoff = now - RETAIN
    deleted = 0

    old = (Message.objects.filter(file_deleted_at__isnull=True, kept_at__isnull=True, created_at__lt=cutoff)
           .exclude(media_file='').exclude(media_file__isnull=True)
           .filter(Q(direction=Message.INBOUND) | Q(sent_by__isnull=False)).exclude(kind__in=OUR_KINDS))
    for chat_id in old.values_list('conversation_id', flat=True).distinct():
        conversation = Conversation.objects.get(pk=chat_id)
        if open_job(conversation) is not None:
            continue                     # what they're printing from, and the proof: after the job
        try:
            deleted += len(delete(conversation, list(old.filter(conversation=conversation)), None, ''))
        except Exception:
            logger.exception('Clean-up failed for chat %s', chat_id)

    kept_prints = {m.file_sha256 for m in Message.objects.filter(kept_at__isnull=False).exclude(file_sha256='')}
    for f in (JobFile.objects.filter(created_at__lt=cutoff).exclude(file='')
              .exclude(job__in=_open(Job.objects.all())).select_related('job')):
        sha = fingerprint(f.file)
        if sha and sha in kept_prints:
            continue
        name = f.file.name.rsplit('/', 1)[-1]
        try:
            with transaction.atomic():
                _gone(f.file)
                record(kinds.FILE_DELETED, actor=Event.OCTOS, job=f.job, reason=OCTOS_REASON,
                       payload={'what': 'job file', 'name': name, 'sha256': sha})
                f.delete()
            deleted += 1
        except Exception:
            logger.exception('Clean-up failed for job file %s', f.pk)

    for f in OrderFile.objects.filter(created_at__lt=cutoff).exclude(file='').select_related('order'):
        sha = fingerprint(f.file)
        if sha and sha in kept_prints:
            continue
        try:
            with transaction.atomic():
                _gone(f.file)
                record(kinds.FILE_DELETED, actor=Event.OCTOS, reason=OCTOS_REASON,
                       payload={'what': 'order file', 'order': f.order.order_number,
                                'name': f.original_filename, 'sha256': sha})
                f.delete()
            deleted += 1
        except Exception:
            logger.exception('Clean-up failed for order file %s', f.pk)
    return deleted


def cleared_since(moment):
    """How many files the clean-up deleted since then: one line in the morning brief."""
    from apps.spine import kinds
    from apps.spine.models import Event
    return Event.objects.filter(kind=kinds.FILE_DELETED, actor=Event.OCTOS, occurred_at__gte=moment).count()
