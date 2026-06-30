"""
Branch Statement PDF builder.

Investor/bank-presentable financial statement for a branch over an
arbitrary date range. Restrained black/gray palette by design — no
brand red, no decoration competing with the numbers.

Page 1: narrative summary, headline metric cards, monthly revenue bar
        chart, payment method breakdown, customer growth signals.
Page 2: calendar-week breakdown table (full precision, week by week).
"""

from decimal import Decimal
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    Image, HRFlowable,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.pdfgen import canvas as pdfcanvas

from django.conf import settings

INK       = colors.HexColor('#18181b')
GRAY_700  = colors.HexColor('#3f3f46')
GRAY_500  = colors.HexColor('#71717a')
GRAY_300  = colors.HexColor('#a1a1aa')
GRAY_BG   = colors.HexColor('#fafafa')
LINE      = colors.HexColor('#e4e4e7')
GREEN     = colors.HexColor('#16a34a')
RED       = colors.HexColor('#dc2626')


def _fmt_ghs(amount) -> str:
    return f"GHS {float(amount or 0):,.2f}"


def _build_styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name='BrandName', fontName='Helvetica', fontSize=15,
        textColor=INK, leading=18,
    ))
    styles.add(ParagraphStyle(
        name='BrandSub', fontName='Helvetica', fontSize=9,
        textColor=GRAY_500, leading=12, spaceBefore=2,
    ))
    styles.add(ParagraphStyle(
        name='DocLabel', fontName='Helvetica', fontSize=8,
        textColor=GRAY_300, alignment=TA_RIGHT, leading=10,
    ))
    styles.add(ParagraphStyle(
        name='DocRange', fontName='Helvetica-Bold', fontSize=10,
        textColor=INK, alignment=TA_RIGHT, leading=13, spaceBefore=3,
    ))
    styles.add(ParagraphStyle(
        name='Narrative', fontName='Helvetica', fontSize=10.5,
        textColor=GRAY_700, leading=17, spaceAfter=20,
    ))
    styles.add(ParagraphStyle(
        name='SectionLabel', fontName='Helvetica-Bold', fontSize=8.5,
        textColor=GRAY_500, leading=11, spaceBefore=4, spaceAfter=8,
    ))
    styles.add(ParagraphStyle(
        name='MetricLabel', fontName='Helvetica', fontSize=8,
        textColor=GRAY_300, leading=10,
    ))
    styles.add(ParagraphStyle(
        name='MetricValue', fontName='Helvetica-Bold', fontSize=15,
        textColor=INK, leading=18, spaceBefore=4,
    ))
    styles.add(ParagraphStyle(
        name='Footer', fontName='Helvetica', fontSize=7.5,
        textColor=GRAY_300, leading=10,
    ))
    return styles


def _header_table(styles, branch, date_from, date_to):
    logo_path = settings.BASE_DIR / 'static' / 'images' / 'farhat_logo_bw.png'
    try:
        logo = Image(str(logo_path), width=16*mm, height=16*mm)
    except Exception:
        logo = Spacer(16*mm, 16*mm)

    brand_block = [
        Paragraph('Farhat Printing Press', styles['BrandName']),
        Paragraph(f'{branch.name} &middot; Accra, Ghana', styles['BrandSub']),
    ]

    doc_block = [
        Paragraph('BRANCH STATEMENT', styles['DocLabel']),
        Paragraph(
            f"{date_from.strftime('%b %d')} &mdash; {date_to.strftime('%b %d, %Y')}",
            styles['DocRange']
        ),
    ]

    t = Table(
        [[logo, brand_block, doc_block]],
        colWidths=[20*mm, 95*mm, 65*mm],
    )
    t.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
    ]))
    return t


def _metric_cards(styles, summary):
    cards = [
        ('TOTAL REVENUE', _fmt_ghs(summary['total_revenue'])),
        ('JOBS COMPLETED', f"{summary['total_jobs']:,}"),
        ('CUSTOMERS SERVED', f"{summary['customer_count']:,}"),
        ('AVG JOB VALUE', _fmt_ghs(summary['avg_job_value'])),
    ]
    cells = []
    for label, value in cards:
        cell = [
            Paragraph(label, styles['MetricLabel']),
            Paragraph(value, styles['MetricValue']),
        ]
        cells.append(cell)

    t = Table([cells], colWidths=[45*mm]*4)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), GRAY_BG),
        ('LEFTPADDING', (0,0), (-1,-1), 10),
        ('RIGHTPADDING', (0,0), (-1,-1), 10),
        ('TOPPADDING', (0,0), (-1,-1), 10),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))
    return t


def _monthly_chart(styles, monthly):
    if not monthly:
        return Paragraph('No monthly data for this period.', styles['Narrative'])

    max_rev = max((float(m['revenue']) for m in monthly), default=1) or 1
    bar_h_max = 60  # points

    drawing_rows = []
    bars = []
    labels = []
    for m in monthly:
        h = max((float(m['revenue']) / max_rev) * bar_h_max, 4)
        bar = Table([['']], colWidths=[18*mm], rowHeights=[h])
        bar.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), INK if m == monthly[-1] else GRAY_300),
        ]))
        bars.append(bar)
        labels.append(Paragraph(m['label'], styles['MetricLabel']))

    bar_row = Table([bars], colWidths=[20*mm]*len(bars))
    bar_row.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'BOTTOM')]))
    label_row = Table([labels], colWidths=[20*mm]*len(labels))

    container = Table([[bar_row], [label_row]], colWidths=[20*mm*len(bars)])
    container.setStyle(TableStyle([
        ('TOPPADDING', (0,0), (-1,-1), 2),
        ('BOTTOMPADDING', (0,0), (-1,0), 4),
    ]))
    return container


def _payment_methods_table(styles, methods):
    rows = [['Payment method', 'Amount', '%']]
    for m in methods:
        rows.append([m['label'], _fmt_ghs(m['amount']), f"{m['pct']}%"])

    t = Table(rows, colWidths=[80*mm, 55*mm, 20*mm])
    t.setStyle(TableStyle([
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 9.5),
        ('TEXTCOLOR', (0,0), (-1,0), GRAY_500),
        ('TEXTCOLOR', (0,1), (0,-1), GRAY_700),
        ('TEXTCOLOR', (1,1), (1,-1), INK),
        ('TEXTCOLOR', (2,1), (2,-1), GRAY_300),
        ('ALIGN', (1,0), (-1,-1), 'RIGHT'),
        ('LINEBELOW', (0,0), (-1,-2), 0.5, LINE),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
    ]))
    return t


def _growth_table(styles, growth):
    rows = [
        ['New customers registered', f"{growth['new_customers']:,}"],
        ['Repeat customer rate', f"{growth['repeat_rate']}%"],
        ['Active credit accounts in good standing',
         f"{growth['credit_accounts_ok']} of {growth['credit_accounts_total']}"],
    ]
    t = Table(rows, colWidths=[120*mm, 35*mm])
    t.setStyle(TableStyle([
        ('FONTSIZE', (0,0), (-1,-1), 9.5),
        ('TEXTCOLOR', (0,0), (0,-1), GRAY_700),
        ('TEXTCOLOR', (1,0), (1,-1), INK),
        ('FONTNAME', (1,0), (1,-1), 'Helvetica-Bold'),
        ('ALIGN', (1,0), (1,-1), 'RIGHT'),
        ('LINEBELOW', (0,0), (-1,-1), 0.5, LINE),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
    ]))
    return t


def _weekly_table(styles, weekly):
    rows = [['Week', 'Jobs', 'Revenue', 'Avg job value']]
    for w in weekly:
        label = f"{w['week_start'].strftime('%d %b')} \u2013 {w['week_end'].strftime('%d %b %Y')}"
        rows.append([
            label,
            f"{w['jobs']:,}",
            _fmt_ghs(w['revenue']),
            _fmt_ghs(w['avg_value']),
        ])

    t = Table(rows, colWidths=[65*mm, 25*mm, 40*mm, 40*mm], repeatRows=1)
    t.setStyle(TableStyle([
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('TEXTCOLOR', (0,0), (-1,0), GRAY_500),
        ('TEXTCOLOR', (0,1), (0,-1), GRAY_700),
        ('TEXTCOLOR', (1,1), (-1,-1), INK),
        ('ALIGN', (1,0), (-1,-1), 'RIGHT'),
        ('LINEBELOW', (0,0), (-1,0), 1, INK),
        ('LINEBELOW', (0,1), (-1,-2), 0.5, LINE),
        ('TOPPADDING', (0,0), (-1,-1), 7),
        ('BOTTOMPADDING', (0,0), (-1,-1), 7),
    ]))
    return t


def build_branch_statement_pdf(payload: dict) -> bytes:
    """
    payload comes from BranchStatementService.generate().
    Returns raw PDF bytes.
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        topMargin=20*mm, bottomMargin=18*mm,
        leftMargin=22*mm, rightMargin=22*mm,
    )
    styles = _build_styles()

    branch    = payload['branch']
    date_from = payload['date_from']
    date_to   = payload['date_to']
    summary   = payload['summary']
    growth    = payload['growth']
    methods   = payload['methods']
    monthly   = payload['monthly']
    weekly    = payload['weekly']

    story = []

    # ── Page 1 ──────────────────────────────────────────────────
    story.append(_header_table(styles, branch, date_from, date_to))
    story.append(Spacer(1, 6))
    story.append(HRFlowable(width='100%', thickness=1.4, color=INK))
    story.append(Spacer(1, 16))

    growth_phrase = ''
    if summary['growth_pct'] is not None:
        direction = 'increase' if summary['growth_pct'] >= 0 else 'decrease'
        growth_phrase = (
            f" \u2014 a <font color='#16a34a'><b>{abs(summary['growth_pct'])}% {direction}</b></font>"
            f" over the prior {summary['period_days']}-day period"
        )

    narrative = (
        f"{branch.name} processed <b>{_fmt_ghs(summary['total_revenue'])}</b> in revenue "
        f"across <b>{summary['total_jobs']:,} jobs</b> for <b>{summary['customer_count']:,} customers</b> "
        f"over this period{growth_phrase}."
    )
    story.append(Paragraph(narrative, styles['Narrative']))

    story.append(_metric_cards(styles, summary))
    story.append(Spacer(1, 24))

    story.append(Paragraph('REVENUE BY MONTH', styles['SectionLabel']))
    story.append(_monthly_chart(styles, monthly))
    story.append(Spacer(1, 22))

    story.append(Paragraph('REVENUE BY PAYMENT METHOD', styles['SectionLabel']))
    story.append(_payment_methods_table(styles, methods))
    story.append(Spacer(1, 22))

    story.append(Paragraph('CUSTOMER GROWTH', styles['SectionLabel']))
    story.append(_growth_table(styles, growth))

    from reportlab.platypus import PageBreak
    story.append(Spacer(1, 1))
    story.append(PageBreak())

    # ── Page 2 ──────────────────────────────────────────────────
    story.append(Paragraph('WEEKLY BREAKDOWN', styles['SectionLabel']))
    story.append(_weekly_table(styles, weekly))

    def _footer(canvas: pdfcanvas.Canvas, doc_):
        canvas.saveState()
        canvas.setFont('Helvetica', 7.5)
        canvas.setFillColor(GRAY_300)
        canvas.drawString(22*mm, 12*mm, f"Generated by Octos \u00b7 {date_to.strftime('%d %b %Y')}")
        canvas.drawRightString(
            A4[0] - 22*mm, 12*mm, f"Page {doc_.page}"
        )
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()