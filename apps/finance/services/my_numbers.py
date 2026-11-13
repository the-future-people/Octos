"""
A cashier's own numbers, for My shift (12 Nov 2026).

Only what a cashier can act on, all from facts Octos already records:

  drawer          what should be in the drawer now: the same rule sign-off
                  uses (CashierFloat.expected_now), so the figure watched all
                  day is the figure counted against
  by_method       today's takings by Cash, MoMo, Card (POS), Split, Wallet
  accuracy        the last sign-offs: exact, or over/short by how much
  wait_to_pay     minutes from a job being recorded to its receipt
  busiest         receipts by hour, and the peak
  whatsapp        receipts sent on WhatsApp, and how many chat customers got one

The small functions take plain lists, so each can be checked on its own.
"""
from collections import Counter
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

EXACT = Decimal('0.01')


def accuracy(floats):
    """[(date, variance)], newest first -> the rows and how many were exact."""
    rows = [{'date': d, 'variance': str(v or 0), 'exact': abs(Decimal(v or 0)) <= EXACT} for d, v in floats]
    return {'shifts': rows, 'exact': sum(1 for r in rows if r['exact']), 'of': len(rows)}


def wait_to_pay(pairs):
    """[(recorded_at, paid_at)] -> average whole minutes, or None."""
    gaps = [(paid - recorded).total_seconds() / 60 for recorded, paid in pairs if recorded and paid and paid >= recorded]
    return round(sum(gaps) / len(gaps)) if gaps else None


def busiest(times):
    """[aware datetimes] -> counts by local hour, and the busiest hour."""
    hours = Counter(timezone.localtime(t).hour for t in times)
    peak = max(hours.items(), key=lambda kv: (kv[1], -kv[0]))[0] if hours else None
    return {'by_hour': [{'hour': h, 'count': hours[h]} for h in sorted(hours)], 'peak_hour': peak,
            'peak_count': hours[peak] if peak is not None else 0}


def whatsapp(receipts):
    """[(sent: bool, from_chat: bool)] -> totals for the WhatsApp receipt figure."""
    receipts = list(receipts)
    return {
        'sent': sum(1 for s, _ in receipts if s),
        'of': len(receipts),
        'chat_customers': sum(1 for _, c in receipts if c),
        'chat_sent': sum(1 for s, c in receipts if s and c),
    }


def by_method(rows):
    """[(method, amount)] -> {method: {'amount', 'count'}} plus the total."""
    out = {}
    total = Decimal('0')
    for method, amount in rows:
        bucket = out.setdefault(method, {'amount': Decimal('0'), 'count': 0})
        bucket['amount'] += Decimal(amount or 0)
        bucket['count'] += 1
        total += Decimal(amount or 0)
    return {'methods': {m: {'amount': str(b['amount']), 'count': b['count']} for m, b in out.items()},
            'total': str(total), 'count': sum(b['count'] for b in out.values())}


def my_numbers(cashier, period='today', now=None):
    """Everything My shift shows, for this cashier."""
    from apps.communications.models import Conversation
    from apps.finance.models import CashierFloat, Receipt

    now = now or timezone.now()
    receipts = Receipt.objects.filter(cashier=cashier, is_void=False).select_related('job')
    if period == '30d':
        receipts = receipts.filter(created_at__gte=now - timedelta(days=30))
    else:
        receipts = receipts.filter(created_at__date=timezone.localtime(now).date())
    receipts = list(receipts)

    chat_jobs = set(Conversation.objects.filter(jobs__in=[r.job_id for r in receipts if r.job_id])
                    .values_list('jobs', flat=True))

    active = (CashierFloat.objects.filter(cashier=cashier, is_signed_off=False)
              .select_related('daily_sheet').order_by('-created_at').first())
    drawer = active.expected_now() if active and active.daily_sheet else None

    signed = (CashierFloat.objects.filter(cashier=cashier, is_signed_off=True)
              .order_by('-signed_off_at')[:7])

    return {
        'period': period,
        'drawer': {k: str(v) for k, v in drawer.items()} if drawer else None,
        'by_method': by_method((r.payment_method, r.amount_paid) for r in receipts),
        'accuracy': accuracy((timezone.localtime(f.signed_off_at).date().isoformat() if f.signed_off_at else None,
                              f.variance) for f in signed),
        'wait_to_pay_minutes': wait_to_pay((r.job.created_at, r.created_at) for r in receipts if r.job_id),
        'busiest': busiest(r.created_at for r in receipts),
        'whatsapp': whatsapp((bool(r.whatsapp_sent_at), r.job_id in chat_jobs) for r in receipts),
    }
