"""
Everything the branch manager reads when reviewing a month before filing.

Days nested inside the weekly filing that covers them, because that is
the shape of the review: a week is what gets filed, and the days are what
it is made of. A day belongs to whichever filing covers its date, which
matters at a month boundary where one calendar week is filed twice.

The checks come along with it so a flagged day carries its reason inline,
and any note already written against that day, so an explanation given
once is not asked for again.
"""

from decimal import Decimal


def _money(sheet):
    return (
        (sheet.total_cash or Decimal('0'))
        + (sheet.total_momo or Decimal('0'))
        + (sheet.total_pos or Decimal('0'))
    )


def get_month_review(branch, month, year):
    from apps.finance.models import (
        CashierFloat, DailySalesSheet, DaySheetNote, WeeklyReport,
    )
    from apps.finance.services.close_checks import check_month

    sheets = list(
        DailySalesSheet.objects
        .filter(branch=branch, date__year=year, date__month=month)
        .order_by('date')
    )
    weeks = list(
        WeeklyReport.objects
        .filter(branch=branch, year=year, month=month)
        .order_by('date_from')
    )

    checks = check_month(branch, month, year)
    flags  = checks['days']

    floats = {
        f.daily_sheet_id: f
        for f in CashierFloat.objects.filter(daily_sheet__in=sheets)
    }

    notes_by_sheet = {}
    for note in DaySheetNote.objects.filter(
        daily_sheet__in=sheets
    ).select_related('author').order_by('created_at'):
        notes_by_sheet.setdefault(note.daily_sheet_id, []).append({
            'id':          note.pk,
            'kind':        note.kind,
            'body':        note.body,
            'author':      note.author.full_name if note.author else None,
            'created_at':  note.created_at.isoformat(),
        })

    def day_payload(sheet):
        cashier_float = floats.get(sheet.pk)
        key = sheet.date.isoformat()
        return {
            'sheet_id':   sheet.pk,
            'date':       key,
            'status':     sheet.status,
            'jobs':       sheet.total_jobs_created or 0,
            'cash':       str(sheet.total_cash or 0),
            'momo':       str(sheet.total_momo or 0),
            'pos':        str(sheet.total_pos or 0),
            'total':      str(_money(sheet)),
            'variance':   str(cashier_float.variance) if cashier_float and cashier_float.variance else None,
            'flags':      flags.get(key, []),
            'notes':      notes_by_sheet.get(sheet.pk, []),
        }

    grouped = []
    claimed = set()
    for week in weeks:
        # A day belongs to the filing whose dates cover it. At a month
        # boundary two filings carry the same week number, and only the
        # dates say which days are whose.
        days = [
            s for s in sheets
            if week.date_from <= s.date <= week.date_to
        ]
        claimed.update(s.pk for s in days)
        payloads = [day_payload(s) for s in days]
        grouped.append({
            'report_id':   week.pk,
            'week_number': week.week_number,
            'date_from':   week.date_from.isoformat(),
            'date_to':     week.date_to.isoformat(),
            'status':      week.status,
            'jobs':        week.total_jobs_created or 0,
            'total':       str(week.total_collected),
            'flag_count':  sum(len(d['flags']) for d in payloads),
            'days':        payloads,
        })

    # Days no filing covers. There should be none — but a day outside every
    # week is exactly the gap that went unnoticed for six months, and it
    # should be visible rather than silently dropped from the review.
    orphans = [day_payload(s) for s in sheets if s.pk not in claimed]

    return {
        'month':            month,
        'year':             year,
        'average_per_job':  str(checks['average_per_job']),
        'day_count':        len(sheets),
        'flagged_count':    len(flags),
        'weeks':            grouped,
        'unfiled_days':     orphans,
    }