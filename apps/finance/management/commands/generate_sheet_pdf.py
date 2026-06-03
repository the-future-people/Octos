"""
Management command: generate_sheet_pdf

Usage:
    python manage.py generate_sheet_pdf --sheet-id 213
    python manage.py generate_sheet_pdf --branch WLB --date 2026-04-28

Generates a 3-page read-only encrypted PDF for a closed daily sales sheet.
Output saved to: media/sheets/sheet_<id>_<date>.pdf
"""

import os
from datetime import datetime
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.conf import settings

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, white
from reportlab.pdfgen import canvas as rl_canvas
from pypdf import PdfReader, PdfWriter

from apps.finance.models import DailySalesSheet
from apps.organization.models import Branch
from apps.jobs.models import Job

W, H = A4

# ── Palette ───────────────────────────────────────────────
FARHAT_RED  = HexColor('#E31E24')
DARK        = HexColor('#1a1a1a')
MID         = HexColor('#555555')
LIGHT       = HexColor('#999999')
BORDER      = HexColor('#e0ddd8')
BG          = HexColor('#f7f6f3')
C_GREEN     = HexColor('#1a7a4a')
C_GREEN_BG  = HexColor('#e6f9f2')
C_AMBER     = HexColor('#b86e00')
C_AMBER_BG  = HexColor('#fff8e6')
C_BLUE      = HexColor('#3355cc')
C_BLUE_BG   = HexColor('#e8f0fe')
C_PURPLE    = HexColor('#6b2fd4')
C_PURPLE_BG = HexColor('#f0e8ff')
C_RED_BG    = HexColor('#fde8e8')
C_RED_TEXT  = HexColor('#cc3300')

MEDIA_ROOT  = getattr(settings, 'MEDIA_ROOT', 'media')
LOGO_WHITE  = os.path.join(MEDIA_ROOT, 'assets', 'farhat_logo_white.png')
LOGO_COLOR  = os.path.join(MEDIA_ROOT, 'assets', 'farhat_logo_color.jpg')


def fmt(val):
    return f"GHS {Decimal(str(val or 0)):,.2f}"

def fmt_short(val):
    return f"{Decimal(str(val or 0)):,.2f}"

# ── Shared utilities ──────────────────────────────────────

def draw_footer(c, page_num, total_pages):
    c.setStrokeColor(BORDER)
    c.setLineWidth(0.5)
    c.line(20*mm, 14*mm, W - 20*mm, 14*mm)
    c.setFont('Helvetica', 7)
    c.setFillColor(LIGHT)
    c.drawString(20*mm, 10*mm, 'Farhat Printing Press — Octos Operations Platform')
    c.drawRightString(W - 20*mm, 10*mm,
        f'CONFIDENTIAL  ·  Page {page_num} of {total_pages}')

def draw_content_header(c, meta, page_title):
    c.drawImage(LOGO_COLOR, 20*mm, H - 14*mm - 10*mm,
                width=12*mm, height=12*mm, mask='auto')
    c.setFont('Helvetica-Bold', 8)
    c.setFillColor(DARK)
    c.drawString(34*mm, H - 17*mm, meta['branch'])
    c.setFont('Helvetica', 7)
    c.setFillColor(LIGHT)
    c.drawString(34*mm, H - 22*mm,
        f"{meta['sheet_number']}  ·  {meta['date']}  ·  {meta['status']}")
    c.setFont('Helvetica-Bold', 9)
    c.setFillColor(FARHAT_RED)
    c.drawRightString(W - 20*mm, H - 17*mm, page_title)
    c.setStrokeColor(BORDER)
    c.setLineWidth(0.5)
    c.line(20*mm, H - 26*mm, W - 20*mm, H - 26*mm)

def section_label(c, x, y, text):
    c.setFont('Helvetica-Bold', 7)
    c.setFillColor(LIGHT)
    c.drawString(x, y, text)

def zone_box(c, x, y, w, h, bg=None, stroke=False):
    c.setFillColor(bg or BG)
    c.setStrokeColor(BORDER)
    c.setLineWidth(0.4)
    c.roundRect(x, y, w, h, 2, fill=1, stroke=1 if stroke else 0)

# ═══════════════════════════════════════════════════════════
# PAGE 1 — COVER
# ═══════════════════════════════════════════════════════════

def draw_cover(c, data):
    meta   = data['meta']
    detail = data['branch_detail']

    sheet_date = datetime.fromisoformat(meta['date'])
    generated  = datetime.now()
    week_num   = sheet_date.isocalendar()[1]
    month_name = sheet_date.strftime('%B')
    year       = sheet_date.year
    day_name   = sheet_date.strftime('%A')
    date_str   = sheet_date.strftime('%d %B %Y')
    time_str   = generated.strftime('%I:%M %p')

    CX      = W / 2
    PANEL_W = W * 0.44
    PANEL_X = (W - PANEL_W) / 2
    PANEL_H = H * 0.50
    PANEL_Y = H - PANEL_H

    c.setFillColor(FARHAT_RED)
    c.rect(PANEL_X, PANEL_Y, PANEL_W, PANEL_H, fill=1, stroke=0)

    LOGO_SIZE = 52*mm
    c.drawImage(LOGO_WHITE,
                CX - LOGO_SIZE/2, PANEL_Y + PANEL_H*0.28,
                width=LOGO_SIZE, height=LOGO_SIZE, mask='auto')

    INFO_Y = PANEL_Y - 18*mm
    c.setFont('Helvetica-Bold', 17)
    c.setFillColor(DARK)
    c.drawCentredString(CX, INFO_Y, meta['branch'].upper())
    INFO_Y -= 7*mm

    RULE_W = 80*mm
    c.setStrokeColor(BORDER)
    c.setLineWidth(0.8)
    c.line(CX - RULE_W/2, INFO_Y, CX + RULE_W/2, INFO_Y)
    INFO_Y -= 8*mm

    c.setFont('Courier-Bold', 12)
    c.setFillColor(FARHAT_RED)
    c.drawCentredString(CX, INFO_Y, 'DAILY SALES SHEET')
    INFO_Y -= 7*mm
    c.setFont('Helvetica', 9)
    c.setFillColor(LIGHT)
    c.drawCentredString(CX, INFO_Y, meta['sheet_number'])
    INFO_Y -= 16*mm

    COL_GAP = 4*mm
    LABEL_W = 42*mm
    TABLE_X = CX - (LABEL_W + COL_GAP + 50*mm) / 2

    rows = [
        ('Branch Code',     meta['branch_code']),
        ('Digital Address', detail['digital_address']),
        ('Branch Manager',  detail['manager']),
        ('Date',            f"{day_name}, {date_str}"),
        ('Week / Month',    f"Week {week_num}  ·  {month_name} {year}"),
        ('Status',          meta['status']),
        ('Generated',       time_str),
    ]
    for label, value in rows:
        c.setFont('Helvetica-Bold', 8)
        c.setFillColor(LIGHT)
        c.drawRightString(TABLE_X + LABEL_W, INFO_Y, label)
        c.setFont('Helvetica', 8)
        c.setFillColor(BORDER)
        c.drawCentredString(TABLE_X + LABEL_W + COL_GAP/2, INFO_Y, '·')
        is_status = label == 'Status'
        c.setFont('Helvetica-Bold' if is_status else 'Helvetica', 9)
        c.setFillColor(FARHAT_RED if is_status else DARK)
        c.drawString(TABLE_X + LABEL_W + COL_GAP, INFO_Y, value)
        INFO_Y -= 7.5*mm

    c.setFont('Helvetica', 7)
    c.setFillColor(LIGHT)
    c.drawCentredString(CX, 14*mm,
        'Farhat Printing Press  ·  STRICTLY CONFIDENTIAL  ·  Internal Use Only')

# ═══════════════════════════════════════════════════════════
# PAGE 2 — OPERATIONAL SUMMARY
# ═══════════════════════════════════════════════════════════

def draw_ops_page(c, data):
    meta = data['meta']
    rev  = data['revenue']
    jobs = data['jobs']
    reg  = data['registration']
    pace = data['pace']
    inv  = data['inventory']
    CW   = W - 40*mm
    LM   = 20*mm
    y    = H - 30*mm

    draw_content_header(c, meta, 'OPERATIONAL SUMMARY')

    # Zone 1 — Revenue
    ZONE_H  = 32*mm
    TOTAL_W = 52*mm
    zone_box(c, LM, y - ZONE_H, CW, ZONE_H, BG)
    c.setFillColor(DARK)
    c.roundRect(LM, y - ZONE_H, TOTAL_W, ZONE_H, 2, fill=1, stroke=0)
    c.setFont('Helvetica-Bold', 7)
    c.setFillColor(HexColor('#aaaaaa'))
    c.drawString(LM + 4*mm, y - 6*mm, 'TOTAL COLLECTED')
    c.setFont('Courier-Bold', 16)
    c.setFillColor(white)
    c.drawString(LM + 4*mm, y - 16*mm, fmt(rev['total']))
    c.setFont('Helvetica', 7)
    c.setFillColor(HexColor('#aaaaaa'))
    c.drawString(LM + 4*mm, y - 22*mm,
        f"Net in till: {fmt(rev['net_cash_in_till'])}")

    right_cards = [
        ('CASH',           rev['cash'],           C_GREEN,  C_GREEN_BG),
        ('MOMO',           rev['momo'],           C_AMBER,  C_AMBER_BG),
        ('POS',            rev['pos'],            C_BLUE,   C_BLUE_BG),
        ('CREDIT SETTLED', rev['credit_settled'], C_PURPLE, C_PURPLE_BG),
    ]
    RC_W = (CW - TOTAL_W - 3*mm - 3*3*mm) / 4
    rx   = LM + TOTAL_W + 3*mm
    for label, val, col, bg in right_cards:
        c.setFillColor(bg)
        c.roundRect(rx, y - ZONE_H + 2*mm, RC_W, ZONE_H - 4*mm, 2, fill=1, stroke=0)
        c.setFont('Helvetica-Bold', 6)
        c.setFillColor(col)
        c.drawString(rx + 2*mm, y - 6*mm, label)
        c.setFont('Helvetica-Bold', 7)
        c.drawString(rx + 2*mm, y - 13*mm, 'GHS')
        c.setFont('Courier-Bold', 12)
        c.drawString(rx + 2*mm, y - 21*mm, fmt_short(val))
        rx += RC_W + 3*mm
    y -= ZONE_H + 4*mm

    # Zone 2 — Jobs + Registration
    HALF    = (CW - 3*mm) / 2
    ZONE2_H = 26*mm
    zone_box(c, LM, y - ZONE2_H, HALF, ZONE2_H, BG)
    section_label(c, LM + 3*mm, y - 3*mm, 'JOBS')

    job_cols = [
        ('TOTAL',     str(jobs['total']),     DARK),
        ('COMPLETE',  str(jobs['complete']),  C_GREEN),
        ('PENDING',   str(jobs['pending']),   C_AMBER),
        ('CANCELLED', str(jobs['cancelled']), C_RED_TEXT),
        ('ROUTED',    str(jobs['routed']),    C_BLUE),
    ]
    jcw = HALF / len(job_cols)
    for i, (lbl, val, col) in enumerate(job_cols):
        jx = LM + i*jcw + 3*mm
        c.setFont('Helvetica-Bold', 18 if i == 0 else 14)
        c.setFillColor(col)
        c.drawString(jx, y - 16*mm, val)
        c.setFont('Helvetica', 6)
        c.setFillColor(LIGHT)
        c.drawString(jx, y - 22*mm, lbl)

    rx2 = LM + HALF + 3*mm
    zone_box(c, rx2, y - ZONE2_H, HALF, ZONE2_H, BG)
    section_label(c, rx2 + 3*mm, y - 3*mm, 'REGISTRATION')

    reg_rate = reg['rate']
    rate_col = C_GREEN if reg_rate >= 60 else (C_AMBER if reg_rate >= 30 else C_RED_TEXT)
    c.setFont('Helvetica-Bold', 24)
    c.setFillColor(rate_col)
    c.drawString(rx2 + 3*mm, y - 18*mm, f"{reg_rate}%")
    c.setFont('Helvetica', 7)
    c.setFillColor(LIGHT)
    c.drawString(rx2 + 3*mm, y - 23*mm, 'of jobs linked to a customer')

    rdx = rx2 + 38*mm
    for val, lbl, col in [
        (str(reg['registered']), 'registered', C_GREEN),
        (str(reg['walkin']),     'walk-in',    MID),
    ]:
        c.setFont('Helvetica-Bold', 13)
        c.setFillColor(col)
        c.drawString(rdx, y - 13*mm, val)
        c.setFont('Helvetica', 6.5)
        c.setFillColor(LIGHT)
        c.drawString(rdx, y - 19*mm, lbl)
        rdx += 18*mm
    y -= ZONE2_H + 4*mm

    # Zone 3 — Analytics
    ZONE3_H    = 22*mm
    zone_box(c, LM, y - ZONE3_H, CW, ZONE3_H, BG)
    section_label(c, LM + 3*mm, y - 3*mm, 'PERFORMANCE ANALYTICS')
    THIRD      = CW / 3
    jobs_per_hr= pace.get('jobs_per_hour')
    pace_chg   = pace.get('pace_change_pct')
    hours_open = pace.get('hours_open')
    avg_today  = pace.get('avg_job_value_today')
    avg_7d     = pace.get('avg_job_value_7d')
    avg_col    = C_GREEN if (avg_today and avg_7d and
                  float(str(avg_today)) >= float(str(avg_7d))) else C_RED_TEXT

    c.setFont('Courier-Bold', 15)
    c.setFillColor(C_BLUE)
    c.drawString(LM + 3*mm, y - 14*mm, f"{jobs_per_hr or '—'} jobs/hr")
    if pace_chg is not None:
        arrow   = '▲' if pace_chg >= 0 else '▼'
        chg_col = C_GREEN if pace_chg >= 0 else C_RED_TEXT
        c.setFont('Helvetica-Bold', 7)
        c.setFillColor(chg_col)
        c.drawString(LM + 3*mm, y - 20*mm,
            f"{arrow} {abs(pace_chg)}% vs yesterday")

    c.setStrokeColor(BORDER)
    c.setLineWidth(0.4)
    c.line(LM + THIRD, y - ZONE3_H + 3*mm, LM + THIRD, y - 4*mm)

    ax = LM + THIRD + 4*mm
    c.setFont('Helvetica-Bold', 7)
    c.setFillColor(LIGHT)
    c.drawString(ax, y - 8*mm, 'AVG JOB VALUE TODAY')
    c.setFont('Courier-Bold', 13)
    c.setFillColor(avg_col)
    c.drawString(ax, y - 16*mm, fmt(avg_today) if avg_today else '—')
    c.setFont('Helvetica', 7)
    c.setFillColor(LIGHT)
    c.drawString(ax, y - 21*mm,
        f"7-day avg: {fmt(avg_7d)}" if avg_7d else '')

    c.line(LM + THIRD*2, y - ZONE3_H + 3*mm, LM + THIRD*2, y - 4*mm)

    hx = LM + THIRD*2 + 4*mm
    c.setFont('Helvetica-Bold', 7)
    c.setFillColor(LIGHT)
    c.drawString(hx, y - 8*mm, 'HOURS OPEN')
    c.setFont('Courier-Bold', 18)
    c.setFillColor(C_PURPLE)
    c.drawString(hx, y - 18*mm, f"{hours_open or '—'}h")
    if pace.get('yesterday_per_hour'):
        c.setFont('Helvetica', 7)
        c.setFillColor(LIGHT)
        c.drawString(hx + 20*mm, y - 12*mm,
            f"Yesterday: {pace['yesterday_per_hour']} jobs/hr")
    y -= ZONE3_H + 4*mm

    # Zone 4 — Inventory
    inv_items = [i for i in inv if i.get('category') != 'Machinery']
    low_items = [i['consumable'] for i in inv_items if i.get('is_low')]
    ZONE4_H   = 8*mm + len(inv_items)*6.5*mm + (7*mm if low_items else 0)
    zone_box(c, LM, y - ZONE4_H, CW, ZONE4_H, BG)
    section_label(c, LM + 3*mm, y - 3*mm, "INVENTORY — TODAY'S CONSUMPTION")

    hy = y - 8*mm
    c.setFillColor(DARK)
    c.rect(LM, hy - 5.5*mm, CW, 5.5*mm, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont('Helvetica-Bold', 6.5)
    for label, x in [
        ('CONSUMABLE', LM+2*mm), ('UNIT', LM+64*mm),
        ('CONSUMED', LM+82*mm), ('CLOSING STOCK', LM+108*mm),
        ('STATUS', LM+142*mm),
    ]:
        c.drawString(x, hy - 4*mm, label)

    iy = hy - 5.5*mm
    for i, item in enumerate(inv_items):
        row_h  = 6.5*mm
        c.setFillColor(white if i % 2 == 0 else HexColor('#faf9f7'))
        c.rect(LM, iy - row_h, CW, row_h, fill=1, stroke=0)
        is_low = item.get('is_low', False)
        c.setFont('Helvetica', 7)
        c.setFillColor(DARK)
        c.drawString(LM+2*mm, iy-4.5*mm, item['consumable'][:38])
        c.setFillColor(MID)
        c.drawString(LM+64*mm, iy-4.5*mm, item['unit'])
        c.setFillColor(DARK)
        c.drawString(LM+82*mm, iy-4.5*mm,
            f"{item['consumed']} {item['unit']}")
        c.setFillColor(C_RED_TEXT if is_low else DARK)
        c.drawString(LM+108*mm, iy-4.5*mm,
            f"{item['closing']} {item['unit']}")
        c.setFont('Helvetica-Bold', 7)
        c.setFillColor(C_RED_TEXT if is_low else C_GREEN)
        c.drawString(LM+142*mm, iy-4.5*mm, 'LOW' if is_low else 'OK')
        c.setStrokeColor(BORDER)
        c.setLineWidth(0.2)
        c.line(LM, iy-row_h, LM+CW, iy-row_h)
        iy -= row_h

    if low_items:
        c.setFillColor(C_RED_BG)
        c.rect(LM, iy-7*mm, CW, 7*mm, fill=1, stroke=0)
        c.setFont('Helvetica-Bold', 7)
        c.setFillColor(C_RED_TEXT)
        c.drawString(LM+3*mm, iy-5*mm,
            f"LOW STOCK ALERT: {', '.join(low_items)}")

# ═══════════════════════════════════════════════════════════
# PAGE 3 — JOB LEDGER + SIGNATURES
# ═══════════════════════════════════════════════════════════

def draw_ledger_page(c, data):
    meta  = data['meta']
    jobs  = data['jobs_list']
    CW    = W - 40*mm
    LM    = 20*mm
    y     = H - 30*mm

    draw_content_header(c, meta, 'JOB LEDGER')
    section_label(c, LM, y,
        f"ALL JOBS — {data['jobs']['total']} TOTAL  ·  {meta['date']}")
    y -= 5*mm

    col_defs = [
        ('#', 8*mm), ('JOB REF', 36*mm), ('TITLE', 48*mm),
        ('CUSTOMER', 32*mm), ('METHOD', 18*mm),
        ('AMOUNT', 26*mm), ('TIME', 12*mm),
    ]

    c.setFillColor(DARK)
    c.rect(LM, y-6.5*mm, CW, 6.5*mm, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont('Helvetica-Bold', 7)
    x = LM + 2*mm
    for h, cw in col_defs:
        c.drawString(x, y-4.5*mm, h)
        x += cw
    y -= 6.5*mm

    for i, job in enumerate(jobs):
        row_h = 6.5*mm
        c.setFillColor(BG if i % 2 == 0 else white)
        c.rect(LM, y-row_h, CW, row_h, fill=1, stroke=0)
        c.setFont('Helvetica', 7.5)
        c.setFillColor(DARK)
        x = LM + 2*mm
        row = [
            str(i+1),
            job['job_number'][-10:],
            (job['title'] or '—')[:26],
            (job.get('customer') or 'Walk-in')[:18],
            job.get('payment_method') or '—',
            f"GHS {job['amount_paid']}",
            job.get('created_at', '—'),
        ]
        for j, (val, (h, cw)) in enumerate(zip(row, col_defs)):
            if h == 'AMOUNT':
                c.setFont('Courier-Bold', 7.5)
                c.drawRightString(x+cw-2*mm, y-4.5*mm, val)
                c.setFont('Helvetica', 7.5)
                c.setFillColor(DARK)
            elif h == 'METHOD':
                col = (C_GREEN if val == 'CASH' else
                       C_AMBER if val == 'MOMO' else C_BLUE)
                c.setFillColor(col)
                c.setFont('Helvetica-Bold', 7)
                c.drawString(x, y-4.5*mm, val)
                c.setFont('Helvetica', 7.5)
                c.setFillColor(DARK)
            else:
                c.drawString(x, y-4.5*mm, str(val))
            x += cw
        c.setStrokeColor(BORDER)
        c.setLineWidth(0.2)
        c.line(LM, y-row_h, LM+CW, y-row_h)
        y -= row_h

    # Totals row
    y -= 2*mm
    c.setFillColor(DARK)
    c.rect(LM, y-7*mm, CW, 7*mm, fill=1, stroke=0)
    c.setFont('Helvetica-Bold', 7.5)
    c.setFillColor(white)
    c.drawString(LM+4*mm, y-5*mm,
        f"TOTAL  ·  {data['jobs']['total']} jobs")
    c.setFont('Courier-Bold', 8)
    c.drawRightString(LM+CW-2*mm, y-5*mm, fmt(data['revenue']['total']))
    y -= 7*mm + 10*mm

    # Signatures
    section_label(c, LM, y, 'AUTHORISATION & SIGN-OFF')
    y -= 5*mm
    SIG_W = (CW - 2*5*mm) / 3
    for i, label in enumerate(['Branch Manager', 'Cashier', 'Reviewed By']):
        sx = LM + i*(SIG_W+5*mm)
        zone_box(c, sx, y-28*mm, SIG_W, 28*mm, BG)
        c.setFont('Helvetica-Bold', 6.5)
        c.setFillColor(LIGHT)
        c.drawString(sx+3*mm, y-5*mm, label.upper())
        c.setStrokeColor(BORDER)
        c.setLineWidth(0.5)
        c.line(sx+3*mm, y-19*mm, sx+SIG_W-3*mm, y-19*mm)
        c.setFont('Helvetica', 6.5)
        c.setFillColor(LIGHT)
        c.drawString(sx+3*mm, y-24*mm, 'Signature & Date')
    y -= 28*mm + 5*mm

    # Closed-by
    closed_at  = meta.get('closed_at', '')
    closed_str = '—'
    if closed_at:
        try:
            closed_str = datetime.fromisoformat(closed_at).strftime(
                '%d %B %Y at %I:%M %p')
        except Exception:
            closed_str = closed_at

    c.setFillColor(C_GREEN_BG)
    c.roundRect(LM, y-10*mm, CW, 10*mm, 3, fill=1, stroke=0)
    c.setFont('Helvetica-Bold', 7.5)
    c.setFillColor(C_GREEN)
    c.drawString(LM+4*mm, y-4*mm,
        f"Closed by {meta['closed_by']}  ·  {closed_str}")
    c.setFont('Helvetica', 7)
    c.setFillColor(LIGHT)
    c.drawString(LM+4*mm, y-9*mm,
        f"Sheet: {meta['sheet_number']}  ·  Branch: {meta['branch']}")


# ═══════════════════════════════════════════════════════════
# DATA BUILDER — pulls from Django ORM
# ═══════════════════════════════════════════════════════════

def build_data(sheet):
    from apps.finance.services.sheet_summary_service import SheetSummaryService
    from apps.jobs.models import Job

    summary = SheetSummaryService.get_summary(sheet, sheet.branch)
    meta    = summary['meta']

    # Branch detail
    branch = sheet.branch
    digital_address = getattr(branch, 'digital_address', '') or \
                      getattr(branch, 'gh_post_address', '') or '—'
    manager_name = '—'
    try:
        from apps.accounts.models import CustomUser
        bm = CustomUser.objects.filter(
            branch=branch, role__name='BRANCH_MANAGER', is_active=True
        ).first()
        if bm:
            manager_name = bm.full_name
    except Exception:
        pass

    # Jobs list
    jobs_qs = Job.objects.filter(
        daily_sheet=sheet
    ).select_related('customer', 'intake_by').order_by('created_at')

    jobs_list = []
    for job in jobs_qs:
        jobs_list.append({
            'job_number'    : job.job_number or f'#{job.pk}',
            'title'         : job.title or '—',
            'job_type'      : job.job_type,
            'status'        : job.status,
            'payment_method': job.payment_method or '—',
            'amount_paid'   : str(job.amount_paid or '0.00'),
            'created_at'    : job.created_at.strftime('%H:%M') if job.created_at else '—',
            'customer'      : job.customer.full_name if job.customer else 'Walk-in',
        })

    return {
        'meta'        : meta,
        'revenue'     : summary['revenue'],
        'jobs'        : summary['jobs'],
        'registration': summary['registration'],
        'pace'        : summary['pace'],
        'inventory'   : summary['inventory'],
        'branch_detail': {
            'digital_address': digital_address,
            'manager'        : manager_name,
        },
        'jobs_list': jobs_list,
    }


# ═══════════════════════════════════════════════════════════
# PDF BUILDER
# ═══════════════════════════════════════════════════════════

def build_pdf(data, output_path):
    tmp = output_path.replace('.pdf', '_tmp.pdf')
    c   = rl_canvas.Canvas(tmp, pagesize=A4)

    draw_cover(c, data)
    draw_footer(c, 1, 3)
    c.showPage()

    draw_ops_page(c, data)
    draw_footer(c, 2, 3)
    c.showPage()

    draw_ledger_page(c, data)
    draw_footer(c, 3, 3)
    c.save()

    reader = PdfReader(tmp)
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    writer.encrypt(
        user_password='',
        owner_password='octos-sheet-readonly',
        use_128bit=True,
    )
    with open(output_path, 'wb') as f:
        writer.write(f)
    os.remove(tmp)


# ═══════════════════════════════════════════════════════════
# MANAGEMENT COMMAND
# ═══════════════════════════════════════════════════════════

class Command(BaseCommand):
    help = 'Generate a 3-page read-only PDF for a closed daily sales sheet'

    def add_arguments(self, parser):
        parser.add_argument('--branch',   type=str, help='Branch code e.g. WLB')
        parser.add_argument('--date',     type=str, help='Date YYYY-MM-DD')
        parser.add_argument('--sheet-id', type=int, help='Direct sheet ID')
        parser.add_argument('--output',   type=str, help='Output path (optional)')

    def handle(self, *args, **options):
        sheet       = self._get_sheet(options)
        output_path = self._resolve_output(sheet, options.get('output'))

        self._ensure_assets()
        data = build_data(sheet)
        build_pdf(data, output_path)

        self.stdout.write(self.style.SUCCESS(f'PDF generated: {output_path}'))

    def _get_sheet(self, options):
        if options.get('sheet_id'):
            try:
                return DailySalesSheet.objects.select_related(
                    'branch', 'opened_by', 'closed_by'
                ).get(pk=options['sheet_id'])
            except DailySalesSheet.DoesNotExist:
                raise CommandError(f"Sheet {options['sheet_id']} not found.")

        branch_code = options.get('branch')
        if not branch_code:
            raise CommandError('Provide --branch or --sheet-id.')

        try:
            branch = Branch.objects.get(code=branch_code.upper())
        except Branch.DoesNotExist:
            raise CommandError(f"Branch '{branch_code}' not found.")

        date_str = options.get('date')
        if date_str:
            try:
                from datetime import datetime as dt
                target_date = dt.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                raise CommandError('Date must be YYYY-MM-DD.')
        else:
            target_date = timezone.localdate()

        try:
            return DailySalesSheet.objects.select_related(
                'branch', 'opened_by', 'closed_by'
            ).get(branch=branch, date=target_date)
        except DailySalesSheet.DoesNotExist:
            raise CommandError(
                f"No sheet for {branch.name} on {target_date}.")

    def _resolve_output(self, sheet, custom_path):
        if custom_path:
            return custom_path
        sheets_dir = os.path.join(MEDIA_ROOT, 'sheets')
        os.makedirs(sheets_dir, exist_ok=True)
        return os.path.join(sheets_dir,
            f"sheet_{sheet.pk}_{sheet.date}.pdf")

    def _ensure_assets(self):
        """Check logo assets exist in media/assets/."""
        assets_dir = os.path.join(MEDIA_ROOT, 'assets')
        os.makedirs(assets_dir, exist_ok=True)
        if not os.path.exists(LOGO_WHITE):
            raise CommandError(
                f"White logo not found at {LOGO_WHITE}. "
                f"Copy farhat_logo_white.png to media/assets/.")
        if not os.path.exists(LOGO_COLOR):
            raise CommandError(
                f"Colour logo not found at {LOGO_COLOR}. "
                f"Copy farhat_logo_color.jpg to media/assets/.")