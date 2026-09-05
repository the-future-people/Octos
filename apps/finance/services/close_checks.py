"""
Simple checks over a month's daily sheets.

The branch manager is meant to look again at every day and every week
before filing. Twenty-six days is more than anyone reads carefully every
time, so this points at the handful worth a second look and leaves the
rest alone.

Deliberately crude. These are not verdicts and they are not fraud
detection: a flagged day is usually a large corporate order, and the
manager's answer is a sentence, not an investigation. The value is that
the sentence gets written before Finance asks for it rather than after.

Extended by adding to CHECKS. Each check takes the day's figures and the
month's context and returns a message or None.
"""

import logging
from decimal import Decimal

logger = logging.getLogger(__name__)

# Above this multiple of the month's average value per job, a day is worth
# explaining; below the lower one, worth a look for work recorded without
# payment. Both were set against a real month: they caught six days in
# twenty-six, which is enough to read and few enough to trust.
HIGH_MULTIPLE = Decimal('1.6')
LOW_MULTIPLE  = Decimal('0.5')

# Below this many jobs the average is not meaningful — one large order on
# a thin day swings it far enough to flag a day nobody would question.
MIN_JOBS_FOR_RATIO = 8


def _money(sheet):
    return (
        (sheet.total_cash or Decimal('0'))
        + (sheet.total_momo or Decimal('0'))
        + (sheet.total_pos or Decimal('0'))
    )


def check_month(branch, month, year):
    """
    Returns {'average_per_job': Decimal, 'days': {date: [messages]}}.

    Compared against the month's own average rather than a rolling one: a
    December is not a June, and the manager is already reading this month
    as a whole.
    """
    from apps.finance.models import CashierFloat, DailySalesSheet

    sheets = list(
        DailySalesSheet.objects
        .filter(branch=branch, date__year=year, date__month=month)
        .order_by('date')
    )
    if not sheets:
        return {'average_per_job': Decimal('0.00'), 'days': {}}

    total_jobs  = sum(s.total_jobs_created or 0 for s in sheets)
    total_money = sum(_money(s) for s in sheets)
    average = (total_money / total_jobs) if total_jobs else Decimal('0.00')

    variances = {
        f.daily_sheet_id: f.variance
        for f in CashierFloat.objects.filter(daily_sheet__in=sheets)
        if f.variance
    }

    days = {}
    for sheet in sheets:
        jobs  = sheet.total_jobs_created or 0
        money = _money(sheet)
        messages = []

        # A contradiction rather than a threshold, and worth catching
        # regardless of size: it is how a stranded sheet or a pricing rule
        # returning zero shows up in the figures.
        if jobs and not money:
            messages.append(f'{jobs} jobs recorded and nothing taken')
        elif money and not jobs:
            messages.append('money taken with no jobs recorded')

        elif jobs >= MIN_JOBS_FOR_RATIO and average:
            per_job = money / jobs
            if per_job > average * HIGH_MULTIPLE:
                messages.append(
                    f'GHS {per_job:.0f} a job, well above the month average '
                    f'of GHS {average:.0f}'
                )
            elif per_job < average * LOW_MULTIPLE:
                messages.append(
                    f'GHS {per_job:.0f} a job, well below the month average '
                    f'of GHS {average:.0f}'
                )

        variance = variances.get(sheet.pk)
        if variance:
            word = 'over' if variance > 0 else 'short'
            messages.append(f'till {word} by GHS {abs(variance):.2f}')

        if messages:
            days[sheet.date.isoformat()] = messages

    return {
        'average_per_job': average.quantize(Decimal('0.01')),
        'days': days,
    }