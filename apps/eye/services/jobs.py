"""
Jobs as a conveyor: where every live job is, and how the line is doing.

Stages follow the job's work axis. A production or design job at
RECEIVED is waiting for inspection; DONE and awaiting collection is
Ready. Instant jobs never touch the line and are counted apart.
"""

from datetime import timedelta

from django.db.models import Avg, Count, F, Q, Sum
from django.utils import timezone

STAGES = [
    ('RECEIVED', 'Inspecting'),
    ('IN_PRODUCTION', 'In press'),
    ('FINISHING', 'Finishing'),
    ('QUALITY_CHECK', 'Final check'),
    ('DONE', 'Ready'),
]
DEAD = ['DRAFT', 'CANCELLED', 'VOIDED']
COUNTER_CHANNELS = ('WALK_IN', 'PROFORMA')


def taken(branch_ids, start, end):
    from apps.jobs.models import Job
    return Job.objects.filter(
        branch_id__in=branch_ids, created_at__gte=start, created_at__lt=end,
    ).exclude(status__in=DEAD)


def live_line(branch_ids):
    from apps.jobs.models import Job
    return (Job.objects
            .filter(branch_id__in=branch_ids, job_type__in=['PRODUCTION', 'DESIGN'])
            .exclude(status__in=DEAD)
            .exclude(handover_state='HANDED_OVER')
            .exclude(payment_state='UNPAID'))


def halted_ids(job_ids):
    from apps.jobs.models import JobHalt
    return set(JobHalt.objects.filter(job_id__in=job_ids, resumed_at__isnull=True)
               .values_list('job_id', flat=True))


def promise_kept(branch_ids, start, end):
    """KEPT out of KEPT + BROKEN, for jobs whose first promise fell in the window."""
    from apps.jobs.models import Job
    qs = Job.objects.filter(branch_id__in=branch_ids,
                            first_promise_at__gte=start, first_promise_at__lt=end)
    kept = qs.filter(promise_state='KEPT').count()
    broken = qs.filter(promise_state='BROKEN').count()
    return (round(kept / (kept + broken) * 100) if kept + broken else None), kept, broken


def finished(branch_ids, start, end) -> int:
    from apps.jobs.models import FinalCheck
    instant = taken(branch_ids, start, end).filter(job_type='INSTANT', work_state='DONE').count()
    checked = (FinalCheck.objects
               .filter(job__branch_id__in=branch_ids, outcome='PASSED',
                       checked_at__gte=start, checked_at__lt=end)
               .values('job_id').distinct().count())
    return instant + checked


def job_card(job, halted):
    state = (job.promise_state or 'ON_TRACK') if job.promise_state in ('ON_TRACK', 'AT_RISK', 'LATE') else 'ON_TRACK'
    return {
        'id': job.pk,
        'code': job.job_number,
        'title': job.title,
        'branch': job.branch.name,
        'channel': 'Online' if job.intake_channel == 'ONLINE' else 'Counter',
        'promise': job.estimated_ready_at.isoformat() if job.estimated_ready_at else None,
        'state': 'LATE' if halted and state == 'ON_TRACK' else state,
        'halted': halted,
        'customer': job.customer.display_name if job.customer_id else '',
    }


def lens(scope, first, last, prev_first, prev_last) -> dict:
    from apps.jobs.models import FinalCheck, JobStep, JobVerification
    from . import periods

    ids = scope.branch_ids
    start, end = periods.bounds(first, last)
    p_start, p_end = periods.bounds(prev_first, prev_last)

    line = list(live_line(ids).select_related('branch', 'customer')[:400])
    halted = halted_ids([j.pk for j in line])
    stages = []
    for code, label in STAGES:
        here = [j for j in line if j.work_state == code
                and (code != 'DONE' or j.handover_state == 'AWAITING_COLLECTION')]
        stages.append({'code': code, 'label': label,
                       'jobs': [job_card(j, j.pk in halted) for j in here]})

    t = taken(ids, start, end)
    by_type = dict(t.values_list('job_type').annotate(n=Count('id')))
    sources = {
        'Counter': t.filter(intake_channel__in=COUNTER_CHANNELS).count(),
        'Online': t.filter(intake_channel='ONLINE').count(),
        'Other remote': t.exclude(intake_channel__in=COUNTER_CHANNELS + ('ONLINE',)).count(),
    }
    kept_pct, kept, broken = promise_kept(ids, start, end)
    prev_kept, _, _ = promise_kept(ids, p_start, p_end)

    collected_jobs = t.model.objects.filter(
        branch_id__in=ids, handed_over_at__gte=start, handed_over_at__lt=end)
    turn = (collected_jobs.filter(job_type='PRODUCTION')
            .annotate(took=F('handed_over_at') - F('created_at'))
            .aggregate(a=Avg('took'))['a'])

    checks = FinalCheck.objects.filter(job__branch_id__in=ids,
                                       checked_at__gte=start, checked_at__lt=end)
    verifs = JobVerification.objects.filter(job__branch_id__in=ids,
                                            created_at__gte=start, created_at__lt=end)
    spoilt = (JobStep.objects.filter(job__branch_id__in=ids, done_at__gte=start, done_at__lt=end)
              .aggregate(s=Sum('quantity_spoilt'))['s'] or 0)

    all_cards = [c for s in stages for c in s['jobs']]
    return {
        'sources': sources,
        'stages': stages,
        'instant_done': by_type.get('INSTANT', 0),
        'collected': collected_jobs.count(),
        'taken': t.count(),
        'taken_change': periods.change(t.count(), taken(ids, p_start, p_end).count()),
        'by_type': {'instant': by_type.get('INSTANT', 0),
                    'production': by_type.get('PRODUCTION', 0),
                    'design': by_type.get('DESIGN', 0)},
        'promises': {'kept_pct': kept_pct, 'kept': kept, 'broken': broken,
                     'prev_kept_pct': prev_kept},
        'turnaround_minutes': round(turn.total_seconds() / 60) if turn else None,
        'late': sum(1 for c in all_cards if c['state'] == 'LATE'),
        'at_risk': sum(1 for c in all_cards if c['state'] == 'AT_RISK'),
        'halted': len(halted),
        'inspection': {'cleared': verifs.filter(outcome='PASSED').count(),
                       'held': verifs.exclude(outcome='PASSED').count()},
        'final_check': {'passed': checks.filter(outcome='PASSED').count(),
                        'sent_back': checks.filter(outcome='SENT_BACK').count()},
        'spoilt_pieces': spoilt,
    }


def journey(job_id) -> dict:
    """Every step of one job, with who did it and when."""
    from apps.jobs.models import Job

    job = (Job.objects.select_related('branch', 'customer', 'intake_by')
           .get(pk=job_id))
    ev = []

    def add(when, label, who='', detail=''):
        if when:
            ev.append({'at': when.isoformat(), 'label': label, 'who': who, 'detail': detail})

    add(job.created_at, 'Taken',
        job.intake_by.full_name if job.intake_by_id else ('Online' if job.intake_channel == 'ONLINE' else ''),
        job.get_intake_channel_display())
    for r in job.receipts.filter(is_void=False).select_related('cashier').order_by('created_at'):
        add(r.created_at, 'Paid', r.cashier.full_name if r.cashier_id else 'Paystack',
            f'{r.get_payment_method_display()} GHS {r.amount_paid}')
    for v in job.verifications.select_related('checked_by').order_by('created_at'):
        add(v.created_at, 'Inspected', v.checked_by.full_name if v.checked_by_id else '',
            v.get_outcome_display())
    for s in job.steps.select_related('machine', 'station', 'started_by', 'done_by').order_by('sequence'):
        where = s.machine.name if s.machine_id else ('bench' if s.by_hand else s.station.name)
        add(s.started_at or s.reached_at, f'Started: {s.station.name}',
            s.started_by.full_name if s.started_by_id else '', where)
        add(s.done_at, f'Done: {s.station.name}', s.done_by.full_name if s.done_by_id else '',
            f'{s.quantity_made or ""} made' + (f', {s.quantity_spoilt} spoilt' if s.quantity_spoilt else ''))
    for h in job.halts.select_related('halted_by').order_by('halted_at'):
        add(h.halted_at, 'Halted', h.halted_by.full_name if h.halted_by_id else '',
            h.get_reason_display())
        add(h.resumed_at, 'Resumed')
    for c in job.final_checks.select_related('checked_by').order_by('checked_at'):
        add(c.checked_at, 'Final check', c.checked_by.full_name if c.checked_by_id else '',
            c.get_outcome_display())
    add(job.handed_over_at, 'Collected',
        job.handed_over_by.full_name if job.handed_over_by_id else '')
    ev.sort(key=lambda e: e['at'])

    halted = job.halts.filter(resumed_at__isnull=True).first()
    return {
        'id': job.pk, 'code': job.job_number, 'title': job.title,
        'customer': job.customer.display_name if job.customer_id else 'Walk-in',
        'branch': job.branch.name, 'channel': job.get_intake_channel_display(),
        'promise': job.estimated_ready_at.isoformat() if job.estimated_ready_at else None,
        'promise_state': job.promise_state,
        'halted': ({'reason': halted.get_reason_display(), 'since': halted.halted_at.isoformat()}
                   if halted else None),
        'events': ev,
    }
