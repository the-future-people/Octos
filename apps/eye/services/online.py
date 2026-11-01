"""
The website, the app, and how strangers become paying customers.

Website visits and store downloads are not recorded in Octos yet. They
are returned as None with a state saying so, never as a guess.
"""

from django.db.models import Count, Q, Sum
from django.utils import timezone

from . import periods


def orders(start, end):
    from apps.storefront.models import OnlineOrder
    return OnlineOrder.objects.filter(created_at__gte=start, created_at__lt=end)


def lens(scope, first, last, prev_first, prev_last) -> dict:
    start, end = periods.bounds(first, last)
    p_start, p_end = periods.bounds(prev_first, prev_last)
    qs = orders(start, end)
    # Orders are company-wide until routed; once routed they carry a branch.
    if scope.kind != 'company':
        qs = qs.filter(branch_id__in=scope.branch_ids)

    carts = qs.exclude(line_items=[]).count()
    checkouts = qs.exclude(payment_reference='').count()
    paid_qs = qs.filter(paid_at__isnull=False)
    paid = paid_qs.count()
    prev_paid = orders(p_start, p_end).filter(paid_at__isnull=False)
    if scope.kind != 'company':
        prev_paid = prev_paid.filter(branch_id__in=scope.branch_ids)

    from . import money
    total = money.collected(scope.branch_ids, start, end)
    online_rev = paid_qs.aggregate(s=Sum('total'))['s'] or 0
    return {
        'funnel': [
            {'stage': 'Visits', 'count': None, 'state': 'NOT_TRACKED'},
            {'stage': 'Carts', 'count': carts},
            {'stage': 'Checkouts', 'count': checkouts},
            {'stage': 'Paid', 'count': paid},
        ],
        'paid': paid,
        'paid_change': periods.change(paid, prev_paid.count()),
        'revenue': online_rev,
        'share_of_revenue': round(float(online_rev) / float(total) * 100) if total else None,
        'abandoned': checkouts - paid if checkouts > paid else 0,
        'texts': {'state': 'NOT_TRACKED'},
    }


def app(first, last, prev_first, prev_last) -> dict:
    from apps.storefront.models import AppNotification, AppSession, DeviceToken

    start, end = periods.bounds(first, last)
    p_start, p_end = periods.bounds(prev_first, prev_last)
    sessions = AppSession.objects.all()

    users = sessions.values('lead_id').distinct().count()
    signed_in = sessions.filter(created_at__gte=start, created_at__lt=end).values('lead_id').distinct().count()
    active = sessions.filter(last_seen_at__gte=start, last_seen_at__lt=end).values('lead_id').distinct().count()
    prev_active = sessions.filter(last_seen_at__gte=p_start, last_seen_at__lt=p_end).values('lead_id').distinct().count()
    live = sessions.filter(revoked_at__isnull=True).values('lead_id').distinct().count()

    platforms = dict(DeviceToken.objects.values_list('platform').annotate(n=Count('id')))

    try:
        with_customer = (sessions.filter(lead__customer__isnull=False)
                         .values('lead__customer_id').distinct().count())
    except Exception:
        with_customer = None

    notes = AppNotification.objects.filter(created_at__gte=start, created_at__lt=end)
    return {
        'downloads': {'state': 'NOT_CONNECTED'},
        'users': users,
        'signed_in_now': live,
        'new_sign_ins': signed_in,
        'active': active,
        'active_change': periods.change(active, prev_active),
        'customers_with_app': with_customer,
        'platforms': {k or 'unknown': v for k, v in platforms.items()},
        'notifications': {'sent': notes.count(), 'pushed': notes.filter(pushed=True).count(),
                          'texted': notes.filter(texted=True).count(),
                          'read': notes.filter(read_at__isnull=False).count()},
        'orders_from_app': {'state': 'NOT_TRACKED'},
    }
