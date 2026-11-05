"""
What Octos's assistant may know: plain facts read from the floor.

Every fact the assistant states must come from one of these tools, and
the checker refuses any reply carrying a price, time, total or status
that didn't. So these return facts only: no wording, no guesses. The
assistant phrases; the tools know.

Each tool returns plain dicts and lists (JSON-ready) to hand to the
language model as tool results.
"""
import logging

from django.db.models import Q
from django.utils import timezone

logger = logging.getLogger(__name__)

# Work stages in the words a customer would use. Every Job.Work value
# needs a line here; an unknown one is logged and passed through, never
# dropped.
WORK_WORDS = {
    'RECEIVED':      'received, not started yet',
    'IN_PRODUCTION': 'being made now',
    'FINISHING':     'being finished (cutting, binding and so on)',
    'QUALITY_CHECK': 'being checked before it goes out',
    'DONE':          'finished',
}


def branch_hours(branch, at=None):
    """
    Whether a branch is open now, today's hours or why it's closed, and
    when it next opens. From the one calendar (organization/services/hours).
    """
    from apps.organization.services import hours

    at = timezone.localtime(at or timezone.now())
    closed = hours.closed_because(branch, at.date())
    return {
        'branch': _branch_name(branch),
        'open_now': hours.is_open(branch, at),
        'today': (
            {'closed': closed} if closed else
            {'opens': _clock(branch.opening_time), 'closes': _clock(branch.closing_time)}
        ),
        'next_opening': _when(hours.next_opening(branch, at), at),
    }


def customer_jobs(phone, at=None, limit=5):
    """
    The customer's open jobs (not yet handed over, not voided or
    abandoned, not drafts), newest first, found by their phone number,
    for walk-ins and online orders alike (conversion always sets the
    customer). The money is Job.balance_due, the same figure the cashier
    sees; never a sum of its own.
    """
    from apps.core.phones import lookup_forms
    from apps.customers.models.customer import CustomerProfile
    from apps.jobs.models import Job

    forms = lookup_forms(phone or '')
    if not forms:
        return {'found': False, 'jobs': []}

    people = CustomerProfile.objects.filter(Q(phone__in=forms) | Q(secondary_phone__in=forms))
    jobs = (
        Job.objects
        .filter(Q(customer__in=people) | Q(ordered_by__in=people))
        .exclude(status=Job.DRAFT)
        .exclude(handover_state=Job.Handover.HANDED_OVER)
        .filter(voided_at__isnull=True, abandoned_at__isnull=True)
        .select_related('branch')
        .order_by('-created_at')
        .distinct()[:limit]
    )
    at = timezone.localtime(at or timezone.now())
    found = [_job_facts(job, at) for job in jobs]
    return {'found': bool(found), 'jobs': found}


def _job_facts(job, at):
    work = job.work_state or ''
    words = WORK_WORDS.get(work)
    if words is None:
        logger.warning('Assistant: job %s has a work stage with no words: %r', job.pk, work)
        words = work.replace('_', ' ').lower() or 'unknown'

    balance = job.balance_due
    return {
        'ref': _ref(job.job_number),
        'what': job.line_item_summary,
        'branch': _branch_name(job.branch),
        'stage': words,
        'ready_to_collect': job.handover_state == job.Handover.AWAITING_COLLECTION,
        'out_for_delivery': job.handover_state == job.Handover.OUT_FOR_DELIVERY,
        'promised_ready': _when(job.estimated_ready_at, at) if job.estimated_ready_at else None,
        'promise': (job.promise_state or '').lower() or None,
        'balance_due': f'GHS {balance:.2f}' if balance is not None else None,
        'paid_in_full': job.is_fully_paid,
    }


def _ref(job_number):
    """The short reference a customer can read out: FP-WLB-2026-05629 is 5629."""
    tail = (job_number or '').rsplit('-', 1)[-1].lstrip('0')
    return tail or job_number or ''


def _branch_name(branch):
    name = (getattr(branch, 'name', '') or '').strip()
    return name[:-7] if name.endswith(' Branch') else name


def _clock(t):
    return t.strftime('%I:%M%p').lstrip('0').lower()


def _when(moment, now):
    """'4:10pm today', '8:00am tomorrow', 'Tue 8:00am': short, clear, local."""
    moment = timezone.localtime(moment)
    clock = _clock(moment.time())
    days = (moment.date() - now.date()).days
    if days == 0:
        return f'{clock} today'
    if days == 1:
        return f'{clock} tomorrow'
    return f'{moment:%a} {clock}'