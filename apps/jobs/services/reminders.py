"""
Reminders to customers (13 Nov 2026), sent once a day by the beat.

  Ready for pickup  after 2 days, once more at 7 days, never more than twice;
                    only for work ready within the last 10 days, so an old
                    backlog is the BM's to clear, not Octos's to message.
  Awaiting feedback a design sample with no reply after 1 day: one nudge per
                    sample sent (a revision's new sample gets its own).

Each is recorded on the spine with an idempotency key (job, step), so a
reminder can never go twice. WhatsApp when the customer's window is open,
SMS otherwise (a reminder after 2 days usually finds the window shut).
"""
import logging
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)

PICKUP_STEPS = ((7, 'day7'), (2, 'day2'))     # latest first: one message per run
PICKUP_STALE_AFTER = 10                        # days: older belongs to the BM
FEEDBACK_AFTER = timedelta(days=1)
FEEDBACK_STALE_AFTER = timedelta(days=7)
ADDRESS = 'Farhat Westland, 63 Westlands Ave'
HOURS = 'Monday to Friday 7:30am to 7:30pm, Saturday 9am to 5:30pm'
WHATSAPP_NUMBER = '055 196 9777'


def pickup_step(days_ready, already_sent):
    """The reminder due for work ready `days_ready` days, or None."""
    if days_ready > PICKUP_STALE_AFTER:
        return None
    for days, step in PICKUP_STEPS:
        if days_ready >= days:
            return None if step in already_sent else step
    return None


def first_name(job):
    from apps.jobs.services.labels import for_whom
    who, _ = for_whom(job)
    word = who.split(' (')[0].split()[0] if who and who != 'Walk-in' else ''
    titles = {'MR', 'MRS', 'MS', 'DR', 'MISS', 'PROF', 'REV'}
    words = who.split(' (')[0].split() if who and who != 'Walk-in' else []
    while words and words[0].rstrip('.').upper() in titles:
        words = words[1:]
    return words[0] if words else word


def items_phrase(job):
    from apps.jobs.services.item_lines import describe_job
    names = [r['name'] for r in describe_job(job.line_items.select_related('service').order_by('position'))
             if not r['is_addon']]
    if not names:
        return 'order'
    if len(names) == 1:
        return names[0]
    return f'{names[0]} and {len(names) - 1} more'


def pickup_texts(name, items, step, ready_on, balance):
    hi = f'Hi {name}' if name else 'Hello'
    owe = f" There's GHS {balance:.2f} left to pay when you collect." if balance and balance > 0 else ''
    if step == 'day2':
        wa = f"{hi} 👋 Your {items} is ready for collection at {ADDRESS}. We're open {HOURS}.{owe}"
        sms = f"{hi}, your {items} is ready for collection at {ADDRESS}. Open {HOURS}.{owe} Farhat Printing Press"
    else:
        wa = (f"{hi}, a gentle reminder: your {items} has been ready since {ready_on} at {ADDRESS}. "
              f"We're keeping it safe for you. Open {HOURS}.{owe}")
        sms = f"{hi}, your {items} has been ready since {ready_on} at {ADDRESS}. Open {HOURS}.{owe} Farhat Printing Press"
    return wa, sms


def feedback_texts(name):
    hi = f'Hi {name}' if name else 'Hello'
    wa = (f"{hi}, have you had a chance to look at your design sample? Reply here with any changes, "
          f"or tell us it's approved and we'll get it printed.")
    sms = (f"{hi}, have you looked at your design sample? Reply on WhatsApp {WHATSAPP_NUMBER} with any changes, "
           f"or to approve it. Farhat Printing Press")
    return wa, sms


def _send(phone, wa_text, sms_text, kind):
    """WhatsApp if the window is open, else SMS. Returns 'whatsapp', 'sms' or ''."""
    from apps.communications.services.whatsapp_outbound import try_send_text
    from apps.storefront.services.sms import send_sms
    if try_send_text(phone, wa_text, kind=kind) is not None:
        return 'whatsapp'
    try:
        return 'sms' if send_sms(phone, sms_text, kind=kind) is not False else ''
    except Exception:
        logger.exception('Reminder SMS failed (%s)', kind)
        return ''


def _ready_at(job):
    from apps.jobs.models import JobStatusLog
    log = (JobStatusLog.objects.filter(job=job, axis=JobStatusLog.Axis.WORK, to_status='DONE')
           .order_by('-transitioned_at').first())
    return log.transitioned_at if log else job.updated_at


def send_pickup_reminders(now=None):
    from apps.jobs.models import Job
    from apps.jobs.services.labels import contact_phone
    from apps.spine import kinds
    from apps.spine.models import Event
    from apps.spine.recorder import record

    now = now or timezone.now()
    sent = 0
    jobs = Job.objects.filter(job_type__in=['PRODUCTION', 'DESIGN'], work_state='DONE',
                              handover_state='AWAITING_COLLECTION').exclude(status='CANCELLED')
    for job in jobs.select_related('customer', 'branch'):
        ready = _ready_at(job)
        days = (timezone.localtime(now).date() - timezone.localtime(ready).date()).days
        done = set(Event.objects.filter(kind=kinds.JOB_PICKUP_REMINDED, job=job)
                   .values_list('payload__step', flat=True))
        step = pickup_step(days, done)
        phone = contact_phone(job)
        if not step or not phone:
            continue
        wa, sms = pickup_texts(first_name(job), items_phrase(job), step,
                               timezone.localtime(ready).strftime('%A %d %B'), job.balance_due)
        how = _send(phone, wa, sms, kind='pickup_reminder')
        if how:
            record(kinds.JOB_PICKUP_REMINDED, job=job, customer=job.customer, branch=job.branch,
                   key=f'pickup-reminder:{job.pk}:{step}', payload={'step': step, 'by': how},
                   reason=f'Reminded to collect ({step}) by {how}.')
            sent += 1
    return sent


def send_feedback_nudges(now=None):
    from apps.jobs.models import Job, JobStatusLog
    from apps.jobs.services.labels import contact_phone
    from apps.spine import kinds
    from apps.spine.recorder import record

    now = now or timezone.now()
    sent = 0
    for job in Job.objects.filter(status='SAMPLE_SENT').select_related('customer', 'branch'):
        log = JobStatusLog.objects.filter(job=job, to_status='SAMPLE_SENT').order_by('-transitioned_at').first()
        if log is None or not (FEEDBACK_AFTER <= now - log.transitioned_at <= FEEDBACK_STALE_AFTER):
            continue
        key = f'feedback-nudge:{job.pk}:{log.pk}'
        from apps.spine.models import Event
        phone = contact_phone(job)
        if Event.objects.filter(idempotency_key=key).exists() or not phone:
            continue
        wa, sms = feedback_texts(first_name(job))
        how = _send(phone, wa, sms, kind='feedback_nudge')
        if how:
            record(kinds.JOB_FEEDBACK_NUDGED, job=job, customer=job.customer, branch=job.branch,
                   key=key, payload={'by': how}, reason=f'Nudged for design feedback by {how}.')
            sent += 1
    return sent
