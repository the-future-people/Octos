"""
Octos's own health: the things that, when they fail, fail silently.
"""

from datetime import timedelta

from django.utils import timezone

PAID_NO_JOB_AFTER = timedelta(minutes=10)


def paid_without_job():
    from apps.storefront.models import OnlineOrder
    cutoff = timezone.now() - PAID_NO_JOB_AFTER
    return (OnlineOrder.objects.filter(paid_at__isnull=False, paid_at__lt=cutoff, job__isnull=True)
            .exclude(status__in=['CANCELLED']).select_related('branch'))


def lens() -> dict:
    from apps.storefront.models import OnlineOrder, PaystackEvent

    last_event = PaystackEvent.objects.order_by('-created_at').values_list('created_at', flat=True).first()
    last_order = OnlineOrder.objects.filter(paid_at__isnull=False).order_by('-paid_at') \
        .values_list('paid_at', flat=True).first()
    stuck = list(paid_without_job()[:20])
    parts = [
        {'part': 'Database', 'state': 'ok', 'note': 'answering'},
        {'part': 'Payments (Paystack)', 'state': 'ok' if last_event else 'unknown',
         'note': f'last event {timezone.localtime(last_event):%d %b %H:%M}' if last_event else 'no events yet'},
        {'part': 'Online orders', 'state': 'ok' if last_order else 'unknown',
         'note': f'last paid {timezone.localtime(last_order):%d %b %H:%M}' if last_order else 'none yet'},
        {'part': 'Background worker', 'state': 'unknown', 'note': 'heartbeat not recorded yet'},
        {'part': 'Texts (mNotify)', 'state': 'unknown', 'note': 'text log not recorded yet'},
    ]
    return {
        'parts': parts,
        'paid_without_job': [{'order': o.order_number, 'paid_at': o.paid_at.isoformat(),
                              'branch': o.branch.name if o.branch_id else ''} for o in stuck],
    }
