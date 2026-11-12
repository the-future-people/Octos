"""
The five workload lists behind the BM Overview tiles (12 Nov 2026).

One definition per list (workload_filter), used by the overview counts
(stats_selectors.get_active_workload) and by each page, so a tile and its
page can never disagree.
"""
from django.db.models import Q


WORKLOAD_VIEWS = ('pending_payment', 'in_production', 'ready_for_pickup',
                  'awaiting_feedback', 'overdue')


def workload_filter(view, now):
    """The jobs a workload view is made of. The single source of truth."""
    if view == 'pending_payment':
        return Q(status='PENDING_PAYMENT')
    if view == 'in_production':
        return Q(status__in=['CONFIRMED', 'IN_PROGRESS'], job_type__in=['PRODUCTION', 'DESIGN'])
    if view == 'ready_for_pickup':
        return Q(status='READY', job_type__in=['PRODUCTION', 'DESIGN'])
    if view == 'awaiting_feedback':
        return Q(status__in=['SAMPLE_SENT', 'REVISION_REQUESTED'])
    if view == 'overdue':
        return Q(deadline__lt=now,
                 status__in=['CONFIRMED', 'IN_PROGRESS', 'READY', 'SAMPLE_SENT', 'REVISION_REQUESTED'])
    raise ValueError(f'Unknown workload view: {view}')


def _for_whom(job):
    from apps.jobs.services.labels import for_whom
    return for_whom(job)


def _recorded_by(job):
    from apps.jobs.services.labels import recorded_by
    return recorded_by(job)


def get_workload_list(branch, view, now=None, limit=200) -> dict:
    """
    One workload view's jobs, with what the BM needs to act on each, and the
    page's summary figures. Built on workload_filter, as the overview's count is.
    """
    from apps.jobs.models import Job, JobLineItem
    from django.utils import timezone

    now = now or timezone.now()
    jobs = list(Job.objects.filter(branch=branch).filter(workload_filter(view, now))
                .select_related('customer', 'intake_by').order_by('created_at')[:limit])

    rows = []
    for job in jobs:
        who, from_chat = _for_whom(job)
        items = [f'{li.quantity} × {li.service.name}' if getattr(li, 'service', None) else ''
                 for li in JobLineItem.objects.filter(job=job).select_related('service')]
        promised = getattr(job, 'estimated_ready_at', None)
        rows.append({
            'id': job.pk,
            'job_number': job.job_number,
            'job_type': job.job_type,
            'status': job.status,
            'for': who,
            'from_chat': from_chat,
            'items': [i for i in items if i],
            'amount': str(job.estimated_cost or 0),
            'recorded_by': _recorded_by(job),
            'work_state': job.work_state,
            'payment_state': job.payment_state,
            'handover_state': job.handover_state,
            'recorded_at': job.created_at,
            'waited_minutes': int((now - job.created_at).total_seconds() // 60),
            'deadline': job.deadline,
            'promised': promised,
            'late_minutes': int((now - job.deadline).total_seconds() // 60) if job.deadline and job.deadline < now else None,
            'updated_at': job.updated_at,
        })

    from decimal import Decimal
    summary = {
        'count': len(rows),
        'total_amount': str(sum((Decimal(r['amount']) for r in rows), Decimal('0'))),
        'oldest_minutes': max((r['waited_minutes'] for r in rows), default=None),
        'from_chat': sum(1 for r in rows if r['from_chat']),
    }
    return {'view': view, 'summary': summary, 'rows': rows}
