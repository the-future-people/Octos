# apps/finance/pdf/weekly_report_pdf.py
"""
The weekly filing PDF.

Moved out of finance/api/views.py, where it sat among three thousand
lines of unrelated API code. The view now imports this and serves what
it returns.

CoverPage lives inside the builder because it closes over the colours
defined there. It reaches for self.canv, which is what ReportLab sets
on a flowable — an earlier version used self.canvas, raised on every
render, and the caller's broad except swallowed it, so the weekly
filing produced no PDF for months without anyone being told.
"""

import os
import calendar

from django.conf import settings

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate, SimpleDocTemplate, PageTemplate, Frame,
    NextPageTemplate, Table, TableStyle, Paragraph, Spacer,
    PageBreak, HRFlowable, Image,
)
from reportlab.platypus.flowables import Flowable


def _generate_weekly_pdf(report):
    """Generate the weekly filing PDF."""
    media_root = getattr(settings, 'MEDIA_ROOT', 'media')
    weekly_dir = os.path.join(media_root, 'weekly')
    os.makedirs(weekly_dir, exist_ok=True)

    output_path = os.path.join(
        weekly_dir,
        f"weekly_{report.branch.code}_W{report.week_number}_{report.year}.pdf"
    )

    branch = report.branch
    W, H = A4

    # Colors
    FARHAT_RED = colors.HexColor('#E31E24')
    FARHAT_GOLD = colors.HexColor('#F5A623')
    WHITE = colors.white
    BLACK = colors.HexColor('#111111')
    GREY = colors.HexColor('#666666')
    LIGHT_GREY = colors.HexColor('#f5f5f5')
    BORDER_GREY = colors.HexColor('#e0e0e0')

    def fmt(n):
        return f"GHS {float(n or 0):,.2f}"

    # Custom cover page flowable
    class CoverPage(Flowable):
        def __init__(self, width, height, branch, report):
            Flowable.__init__(self)
            self.width = width
            self.height = height
            self.branch = branch
            self.report = report

        def draw(self):
            # ReportLab sets self.canv on the flowable during drawOn.
            # There is no self.canvas, so this raised on every render and
            # the caller's except swallowed it — the weekly filing has
            # never produced a PDF.
            c = self.canv
            W = self.width
            H = self.height

            # White background
            c.setFillColor(WHITE)
            c.rect(0, 0, W, H, fill=1, stroke=0)

            # Red center panel (60% width, full height)
            panel_x = W * 0.20
            panel_w = W * 0.60
            c.setFillColor(FARHAT_RED)
            c.rect(panel_x, 0, panel_w, H, fill=1, stroke=0)

            # Logo area (white bird silhouette approximation)
            logo_cx = panel_x + panel_w / 2
            logo_cy = H * 0.72
            logo_r = 28

            c.setFillColor(WHITE)
            c.circle(logo_cx, logo_cy, logo_r, fill=1, stroke=0)

            # Draw stylized F in the circle
            c.setFillColor(FARHAT_RED)
            c.setFont('Helvetica-Bold', 22)
            c.drawCentredString(logo_cx, logo_cy - 8, 'F')

            # Branch name
            branch_name = self.branch.name.upper()
            words = branch_name.split()
            if len(words) >= 2:
                line1 = ' '.join(words[:-1])
                line2 = words[-1]
            else:
                line1 = branch_name
                line2 = ''

            c.setFillColor(WHITE)
            c.setFont('Helvetica-Bold', 32)
            c.drawCentredString(logo_cx, H * 0.55, line1)
            if line2:
                c.drawCentredString(logo_cx, H * 0.47, line2)

            # Week / Month / Year
            month_name = calendar.month_name[self.report.date_from.month].upper()
            week_str = f"WEEK {self.report.week_number},  {month_name},  {self.report.year}"

            c.setFillColor(FARHAT_GOLD)
            c.setFont('Helvetica-Bold', 14)
            c.drawCentredString(logo_cx, H * 0.36, week_str)

            # Contact info
            email = self.branch.email or 'info@farhatprintingpress.com'
            phone = self.branch.phone or self.branch.whatsapp_number or '+233 556244194'

            c.setFillColor(WHITE)
            c.setFont('Helvetica-Bold', 11)
            c.drawCentredString(logo_cx, H * 0.26, email)
            c.drawCentredString(logo_cx, H * 0.21, phone)

            # Footer
            c.setFillColor(FARHAT_GOLD)
            c.setFont('Helvetica-Bold', 7)
            c.drawCentredString(logo_cx, H * 0.07, 'MANDATORY WEEKLY FILING')
            c.drawCentredString(logo_cx, H * 0.055, 'STRICTLY CONFIDENTIAL')

            c.setFillColor(WHITE)
            c.setFont('Helvetica', 7)
            c.drawCentredString(logo_cx, H * 0.035, 'Property of Farhat Printing Press')

    # Build document
    doc = BaseDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=20*mm,
        leftMargin=20*mm,
        topMargin=20*mm,
        bottomMargin=20*mm,
    )

    # Cover page template - full bleed, no margins
    cover_frame = Frame(0, 0, W, H, leftPadding=0, rightPadding=0,
                        topPadding=0, bottomPadding=0, id='cover')
    content_frame = Frame(20*mm, 20*mm, W - 40*mm, H - 40*mm, id='normal')

    doc.addPageTemplates([
        PageTemplate(id='Cover', frames=cover_frame),
        PageTemplate(id='Later', frames=content_frame),
    ])

    styles = getSampleStyleSheet()

    story = []

    # Page 1 - Cover (full bleed)
    story.append(CoverPage(W, H, branch, report))
    story.append(PageBreak())

    # Content page styles
    CW = A4[0] - 40*mm

    h1_style = ParagraphStyle('h1', fontSize=18, fontName='Helvetica-Bold',
                               textColor=BLACK, spaceAfter=4)
    label_style = ParagraphStyle('lbl', fontSize=8, fontName='Helvetica-Bold',
                                  textColor=GREY, letterSpacing=0.5, spaceAfter=8)
    body_style = ParagraphStyle('body', fontSize=9, fontName='Helvetica', textColor=GREY)
    right_style = ParagraphStyle('right', fontSize=9, fontName='Helvetica',
                                  alignment=TA_RIGHT, textColor=BLACK)
    right_bold = ParagraphStyle('rightb', fontSize=10, fontName='Helvetica-Bold',
                                 alignment=TA_RIGHT, textColor=BLACK)

    # Page 2 header
    month_name = calendar.month_name[report.date_from.month]
    story.append(Paragraph(f"{branch.name}", h1_style))
    story.append(Paragraph(
        f"Weekly Filing - Week {report.week_number}, {month_name} {report.year}  "
        f"({report.date_from.strftime('%d %b')} - {report.date_to.strftime('%d %b %Y')})",
        label_style
    ))
    story.append(HRFlowable(width=CW, thickness=2, color=FARHAT_RED))
    story.append(Spacer(1, 6*mm))

    # Revenue summary
    story.append(Paragraph('REVENUE SUMMARY', label_style))

    rev_data = [
        ['Method', 'Amount (GHS)', '% of Total'],
        ['Cash', f"{float(report.total_cash):,.2f}",
         f"{float(report.total_cash)/float(report.total_collected)*100:.1f}%" if report.total_collected else '0%'],
        ['Mobile Money', f"{float(report.total_momo):,.2f}",
         f"{float(report.total_momo)/float(report.total_collected)*100:.1f}%" if report.total_collected else '0%'],
        ['POS', f"{float(report.total_pos):,.2f}",
         f"{float(report.total_pos)/float(report.total_collected)*100:.1f}%" if report.total_collected else '0%'],
        ['TOTAL COLLECTED', f"{float(report.total_collected):,.2f}", '100%'],
        ['Petty Cash Out', f"({float(report.total_petty_cash_out):,.2f})", ''],
        ['Net Cash in Till', f"{float(report.net_cash_in_till):,.2f}", ''],
    ]

    rev_table = Table(rev_data, colWidths=[CW*0.45, CW*0.30, CW*0.25])
    rev_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), LIGHT_GREY),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('FONTNAME', (0, 4), (-1, 4), 'Helvetica-Bold'),
        ('BACKGROUND', (0, 4), (-1, 4), colors.HexColor('#fff0f0')),
        ('TEXTCOLOR', (0, 4), (-1, 4), FARHAT_RED),
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER_GREY),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(rev_table)
    story.append(Spacer(1, 6*mm))

    # Daily breakdown
    story.append(Paragraph('DAILY BREAKDOWN', label_style))

    day_headers = ['Date', 'Day', 'Status', 'Cash', 'MoMo', 'POS', 'Total', 'Jobs']
    day_data = [day_headers]

    sheets = report.daily_sheets.all().order_by('date')
    for sheet in sheets:
        day_name = sheet.date.strftime('%A')
        total = float(sheet.total_cash + sheet.total_momo + sheet.total_pos)
        day_data.append([
            sheet.date.strftime('%d %b'),
            day_name,
            sheet.status,
            f"{float(sheet.total_cash):,.2f}",
            f"{float(sheet.total_momo):,.2f}",
            f"{float(sheet.total_pos):,.2f}",
            f"{total:,.2f}",
            str(sheet.total_jobs_created),
        ])

    if day_data[1:]:
        day_table = Table(
            day_data,
            colWidths=[CW*0.1, CW*0.12, CW*0.11, CW*0.14, CW*0.14, CW*0.12, CW*0.14, CW*0.09]
        )
        day_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), LIGHT_GREY),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('ALIGN', (3, 0), (-1, -1), 'RIGHT'),
            ('GRID', (0, 0), (-1, -1), 0.5, BORDER_GREY),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [WHITE, colors.HexColor('#fafafa')]),
        ]))
        story.append(day_table)
    else:
        story.append(Paragraph('No daily sheets linked.', body_style))

    story.append(Spacer(1, 6*mm))

    # Jobs summary
    story.append(Paragraph('JOBS SUMMARY', label_style))

    jobs_data = [
        ['Metric', 'Count'],
        ['Total Jobs Created', str(report.total_jobs_created)],
        ['Completed', str(report.total_jobs_complete)],
        ['Cancelled', str(report.total_jobs_cancelled)],
        ['Carry Forward (Unpaid)', str(report.carry_forward_count)],
    ]

    jobs_table = Table(jobs_data, colWidths=[CW*0.65, CW*0.35])
    jobs_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), LIGHT_GREY),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER_GREY),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [WHITE, colors.HexColor('#fafafa')]),
    ]))
    story.append(jobs_table)
    story.append(Spacer(1, 6*mm))

    # Inventory
    story.append(Paragraph('INVENTORY', label_style))
    snapshot = report.inventory_snapshot
    items = snapshot.get('items', []) if snapshot else []
    low_stock = snapshot.get('low_stock', []) if snapshot else []

    if items:
        inv_headers = ['Consumable', 'Category', 'Unit', 'Opening', 'Received', 'Consumed', 'Closing', 'Status']
        inv_data = [inv_headers]
        for item in items:
            is_low = item.get('is_low', False)
            status_label = 'LOW' if is_low else 'OK'
            inv_data.append([
                item.get('consumable', '--'),
                item.get('category', '--'),
                item.get('unit', '--'),
                str(item.get('opening', 0)),
                str(item.get('received', 0)),
                str(item.get('consumed', 0)),
                str(item.get('closing', 0)),
                status_label,
            ])

        col_w = [CW*0.28, CW*0.12, CW*0.07, CW*0.08, CW*0.09, CW*0.09, CW*0.08, CW*0.09]
        inv_table = Table(inv_data, colWidths=col_w, repeatRows=1)

        # Build row styles - highlight low stock rows red
        row_styles = [
            ('BACKGROUND', (0, 0), (-1, 0), LIGHT_GREY),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('ALIGN', (3, 0), (-1, -1), 'RIGHT'),
            ('GRID', (0, 0), (-1, -1), 0.5, BORDER_GREY),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [WHITE, colors.HexColor('#fafafa')]),
        ]
        for i, item in enumerate(items, start=1):
            if item.get('is_low', False):
                row_styles.append(('TEXTCOLOR', (7, i), (7, i), FARHAT_RED))
                row_styles.append(('FONTNAME', (7, i), (7, i), 'Helvetica-Bold'))

        inv_table.setStyle(TableStyle(row_styles))
        story.append(inv_table)

        if low_stock:
            story.append(Spacer(1, 3*mm))
            story.append(Paragraph(
                f"<font color='#E31E24'><b>Low stock alert:</b></font> {', '.join(low_stock)}",
                body_style
            ))
    else:
        inv_placeholder = Table([['No inventory data available for this period.']], colWidths=[CW])
        inv_placeholder.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#fffbec')),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#7a5c00')),
            ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#f0d878')),
            ('TOPPADDING', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
            ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ]))
        story.append(inv_placeholder)

    story.append(Spacer(1, 6*mm))

    # BM Notes
    story.append(Paragraph('BRANCH MANAGER NOTES', label_style))
    notes_text = report.bm_notes or '--'
    notes_table = Table([[notes_text]], colWidths=[CW])
    notes_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f9f9f9')),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('TEXTCOLOR', (0, 0), (-1, -1), BLACK),
        ('BOX', (0, 0), (-1, -1), 0.5, BORDER_GREY),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
    ]))
    story.append(notes_table)
    story.append(Spacer(1, 8*mm))

    # Sign-off block
    story.append(HRFlowable(width=CW, thickness=1, color=BORDER_GREY))
    story.append(Spacer(1, 4*mm))

    submitted_by = report.submitted_by.full_name if report.submitted_by else '--'
    submitted_at = (
        report.submitted_at.strftime('%d %b %Y, %I:%M %p')
        if report.submitted_at else '--'
    )

    signoff_data = [
        ['Filed by', submitted_by, 'Date', submitted_at],
        ['Branch', branch.name, 'Week', f"W{report.week_number}/{report.year}"],
    ]
    signoff_table = Table(signoff_data, colWidths=[CW*0.15, CW*0.35, CW*0.15, CW*0.35])
    signoff_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('TEXTCOLOR', (0, 0), (0, -1), GREY),
        ('TEXTCOLOR', (2, 0), (2, -1), GREY),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(signoff_table)
    story.append(Spacer(1, 4*mm))
    story.append(Paragraph(
        'This document is the property of Farhat Printing Press. '
        'Strictly confidential - for internal use only.',
        ParagraphStyle('ft', fontSize=7, fontName='Helvetica',
                       textColor=GREY, alignment=TA_CENTER)
    ))

    doc.build(story)

    # Save path
    report.pdf_path = output_path
    report.save(update_fields=['pdf_path', 'updated_at'])


# ============================================================================
# Monthly Close
# ============================================================================

