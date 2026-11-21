"""
What a customer owes us: one definition, everywhere (21 Nov 2026).

Money owed used to mean "a deposit was paid and the rest is due", counted
separately by the cashier's Balances, the owner line's who-owes and the
Eye's money lens. Work delivered and never paid (Mr. Dwumfour's, on a
proforma that quietly expired) was owed nowhere. Now one rule, here:

  a job owes us its balance when
    - a deposit was paid and the rest is due, or
    - it has been handed over without being paid in full

and every place that shows money owed (Balances, who owes, the money
lens, the customer's statement) asks this module, so they always agree.
Credit accounts stay as they are: a separate, agreed arrangement.
"""
from decimal import Decimal

from django.db.models import Q

ZERO = Decimal('0.00')
CURRENT_DAYS = 30
DEAD = ('CANCELLED', 'VOIDED')

OWING = Q(payment_state='DEPOSIT_PAID') | Q(payment_state='UNPAID', handover_state='HANDED_OVER')


def owing_jobs(branch_ids=None, customer=None):
    """Jobs that owe us a balance, oldest first."""
    from apps.jobs.models import Job
    jobs = Job.objects.filter(OWING).exclude(status__in=DEAD)
    if branch_ids is not None:
        jobs = jobs.filter(branch_id__in=branch_ids)
    if customer is not None:
        jobs = jobs.filter(customer=customer)
    return jobs.select_related('customer', 'branch').order_by('created_at', 'pk')


def is_owing(job):
    """This job owes us its balance (the same rule as OWING, for one job in hand)."""
    if job.status in DEAD:
        return False
    return job.payment_state == 'DEPOSIT_PAID' or (
        job.payment_state == 'UNPAID' and job.handover_state == 'HANDED_OVER')


def balance(job):
    return job.balance_due or ZERO


def statement(customer, branch_ids=None):
    """
    Everything a customer owes, for the statement and for Octos:
      owed      jobs owing a balance (delivered unpaid, or a deposit paid)
      current   jobs taken and waiting for payment (the new work), from the
                last CURRENT_DAYS: an unpaid job left months ago isn't owed
      total     both together
    """
    from datetime import timedelta

    from django.utils import timezone

    from apps.jobs.models import Job
    owed = [j for j in owing_jobs(branch_ids, customer) if balance(j) > 0]
    current = Job.objects.filter(customer=customer, payment_state='UNPAID', status=Job.PENDING_PAYMENT,
                                 created_at__gte=timezone.now() - timedelta(days=CURRENT_DAYS)) \
        .exclude(handover_state='HANDED_OVER')
    if branch_ids is not None:
        current = current.filter(branch_id__in=branch_ids)
    current = [j for j in current.order_by('created_at', 'pk') if balance(j) > 0]
    owed_total = sum((balance(j) for j in owed), ZERO)
    current_total = sum((balance(j) for j in current), ZERO)
    return {'customer': customer, 'owed': owed, 'current': current,
            'owed_total': owed_total, 'current_total': current_total,
            'total': owed_total + current_total}
