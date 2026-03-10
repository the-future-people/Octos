"""
Analytics service.

Usage:

    from apps.analytics.services import compute_snapshot, get_branch_summary

    # Compute and save today's snapshot for a branch
    snapshot = compute_snapshot(branch)

    # Get live summary (no DB write — for API responses)
    summary = get_branch_summary(branch)
"""

import logging
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Avg, Count, Sum, Q

logger = logging.getLogger(__name__)


def get_branch_summary(branch) -> dict:
    """
    Compute live branch metrics without writing to the DB.
    Used by the analytics API for the dashboard summary endpoint.
    """
    try:
        from apps.jobs.models import Job
        jobs = Job.objects.filter(branch=branch)

        total       = jobs.count()
        pending     = jobs.filter(status='PENDING').count()
        in_progress = jobs.filter(status='IN_PROGRESS').count()
        completed   = jobs.filter(status='COMPLETED').count()
        cancelled   = jobs.filter(status='CANCELLED').count()
        routed_out  = jobs.exclude(routed_to=None).count()

        revenue_qs  = jobs.filter(status='COMPLETED').aggregate(
            total=Sum('final_price'),
            avg=Avg('final_price'),
        )
        total_revenue = revenue_qs['total'] or Decimal('0')
        avg_value     = revenue_qs['avg']   or Decimal('0')

    except Exception as exc:
        logger.warning('get_branch_summary: jobs query failed: %s', exc)
        total = pending = in_progress = completed = cancelled = routed_out = 0
        total_revenue = avg_value = Decimal('0')

    try:
        from apps.communications.models import Conversation
        convos         = Conversation.objects.filter(branch=branch)
        total_convos   = convos.count()
        unread_convos  = convos.filter(status='OPEN').count()
        resolved_convos = convos.filter(status='RESOLVED').count()
    except Exception as exc:
        logger.warning('get_branch_summary: comms query failed: %s', exc)
        total_convos = unread_convos = resolved_convos = 0

    completion_rate = round((completed / total * 100), 1) if total > 0 else 0

    # Resolve region and belt via FK traversal
    try:
        region      = branch.region
        region_name = region.name if region else None
        belt_name   = region.belt.name if region and region.belt else None
    except Exception:
        region_name = None
        belt_name   = None

    load_pct = round((branch.current_load / branch.capacity_score * 100), 1) if branch.capacity_score else 0

    return {
        'branch_id':   branch.pk,
        'branch_name': branch.name,
        'region_name': region_name,
        'belt_name':   belt_name,
        'load_percentage': load_pct,
        'jobs': {
            'total':       total,
            'pending':     pending,
            'in_progress': in_progress,
            'completed':   completed,
            'cancelled':   cancelled,
            'routed_out':  routed_out,
            'completion_rate': completion_rate,
        },
        'revenue': {
            'total':     float(total_revenue),
            'avg_value': float(avg_value),
        },
        'communications': {
            'total':    total_convos,
            'unread':   unread_convos,
            'resolved': resolved_convos,
        },
    }


def compute_snapshot(branch, snapshot_date=None):
    """
    Compute metrics for a branch and save a BranchSnapshot.
    Upserts — safe to call multiple times on the same day.
    """
    from .models import BranchSnapshot

    if snapshot_date is None:
        snapshot_date = date.today()

    summary = get_branch_summary(branch)

    jobs  = summary['jobs']
    rev   = summary['revenue']
    comms = summary['communications']

    snapshot, _ = BranchSnapshot.objects.update_or_create(
        branch=branch,
        date=snapshot_date,
        defaults={
            'total_jobs':             jobs['total'],
            'pending_jobs':           jobs['pending'],
            'in_progress_jobs':       jobs['in_progress'],
            'completed_jobs':         jobs['completed'],
            'cancelled_jobs':         jobs['cancelled'],
            'routed_out_jobs':        jobs['routed_out'],
            'total_revenue':          rev['total'],
            'avg_job_value':          rev['avg_value'],
            'total_conversations':    comms['total'],
            'unread_conversations':   comms['unread'],
            'resolved_conversations': comms['resolved'],
            'load_percentage':        summary['load_percentage'],
        }
    )
    logger.info('Snapshot saved: %s | %s', branch, snapshot_date)
    return snapshot


def get_branch_trend(branch, days=30) -> list:
    """
    Return the last N days of snapshots for a branch.
    Used for the trend chart in the analytics API.
    """
    from .models import BranchSnapshot

    since = date.today() - timedelta(days=days)
    qs    = BranchSnapshot.objects.filter(
        branch=branch,
        date__gte=since,
    ).order_by('date')

    return [
        {
            'date':            str(s.date),
            'total_jobs':      s.total_jobs,
            'completed_jobs':  s.completed_jobs,
            'total_revenue':   float(s.total_revenue),
            'load_percentage': float(s.load_percentage),
            'completion_rate': s.completion_rate,
        }
        for s in qs
    ]