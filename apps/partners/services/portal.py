"""
What a partner sees on its dashboard (23 Nov 2026): jobs in progress and
ready to collect, what the trade price has saved it this month, its
rewards progress, and its jobs with its own references.
"""
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from apps.partners.services.pricing import progress

STAGE_LABELS = {
    'paid': 'In the queue', 'received': 'In the queue', 'production': 'Printing',
    'printing': 'Printing', 'finishing': 'Finishing', 'ready': 'Ready to collect',
    'collected': 'Collected', 'cancelled': 'Cancelled',
}


def _job_row(order):
    from apps.communications.assistant.tools import _about
    from apps.storefront.services.accounts import _detail, _stage
    lines = order.line_items or []
    first = lines[0] if lines else {}
    name = first.get('service_name', 'Job')
    stage = _stage(order)
    job = order.job
    if job is not None and job.status in ('CANCELLED', 'VOIDED'):
        stage = 'cancelled'
    row = {
        'order_number': order.order_number,
        'token': order.access_token,
        'reference': order.partner_reference,
        'job_number': job.job_number if job else '',
        'summary': name if len(lines) <= 1 else f'{name} and {len(lines) - 1} more',
        'detail': _detail(first) if first else '',
        'stage': stage,
        'stage_label': STAGE_LABELS.get(stage, 'In the queue'),
        'total': f'{order.total:.2f}',
        'paid_at': order.paid_at.isoformat() if order.paid_at else None,
    }
    if stage not in ('ready', 'collected', 'cancelled'):
        promise = (job.estimated_ready_at if job else None) or order.promised_for
        row['ready_about'] = _about(promise, timezone.now()) if promise else ''
    if stage == 'ready':
        row['collection_code'] = order.collection_pin
    return row


def dashboard(partner, limit=20):
    from apps.storefront.models import OnlineOrder
    paid = (OnlineOrder.objects.filter(partner=partner, paid_at__isnull=False)
            .select_related('job').order_by('-paid_at'))
    rows = [_job_row(o) for o in paid[:limit]]
    start = timezone.localtime().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    saved = paid.filter(paid_at__gte=start).aggregate(s=Sum('discount_amount'))['s'] or Decimal('0')
    every = [_job_row(o) for o in paid.exclude(job__handover_state='HANDED_OVER')[:100]]
    return {
        'stats': {
            'printing': sum(1 for r in every if r['stage'] not in ('ready', 'collected', 'cancelled')),
            'ready': sum(1 for r in every if r['stage'] == 'ready'),
            'saved_this_month': f'{saved:.2f}',
        },
        'rewards': progress(partner),
        'jobs': rows,
        'ready': [r for r in every if r['stage'] == 'ready'],
    }
