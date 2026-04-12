"""
Management command: generate_sheet_pdf

Usage:
    python manage.py generate_sheet_pdf --branch NTB --date 2026-03-15
    python manage.py generate_sheet_pdf --sheet-id 7

Generates a non-editable, password-protected PDF of a daily sales sheet.
Output saved to: media/sheets/sheet_<id>_<date>.pdf
"""

import os
from decimal import Decimal
from datetime import date as date_type

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.conf import settings

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, black, white, grey
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.pdfgen import canvas as rl_canvas
from pypdf import PdfReader, PdfWriter

from apps.finance.models import DailySalesSheet
from apps.organization.models import Branch
from apps.jobs.models import Job


# ── Colour palette ──────────────────────────────────────────────
C_BLACK     = HexColor('#1a1a1a')
C_DARK      = HexColor('#2c2c2c')
C_MID       = HexColor('#555550')
C_LIGHT     = HexColor('#9a9690')
C_BORDER    = HexColor('#e8e5df')
C_BG        = HexColor('#f2f0eb')
C_GREEN     = HexColor('#22c98a')
C_GREEN_BG  = HexColor('#edfaf4')
C_AMBER     = HexColor('#e8c84a')
C_AMBER_BG  = HexColor('#fffbec')
C_BLUE      = HexColor('#3355cc')
C_BLUE_BG   = HexColor('#eef3ff')
C_RED       = HexColor('#e8294a')
C_WHITE     = white


class NumberedCanvas(rl_canvas.Canvas):
    """Canvas subclass that adds a watermark to every page."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        for i, state in enumerate(self._saved_page_states):
            self.__dict__.update(state)
            self._draw_footer(i + 1, len(self._saved_page_states))
            super().showPage()
        super().save()

    def _draw_footer(self, page_num, total_pages):
        self.saveState()
        w, h = A4

        # Bottom rule
        self.setStrokeColor(C_BORDER)
        self.setLineWidth(0.5)
        self.line(20*mm, 14*mm, w - 20*mm, 14*mm)

        # Footer text
        self.setFont('Helvetica', 7)
        self.setFillColor(C_LIGHT)
        self.drawString(20*mm, 10*mm, 'Farhat Printing Press — Octos Operations Platform')
        self.drawRightString(
            w - 20*mm, 10*mm,
            f'CONFIDENTIAL — Page {page_num} of {total_pages}'
        )

        # CLOSED watermark
        self.setFont('Helvetica-Bold', 52)
        self.setFillColor(HexColor('#eeece8'))
        self.saveState()
        self.translate(w / 2, h / 2)
        self.rotate(45)
        self.drawCentredString(0, 0, 'CLOSED')
        self.restoreState()

        self.restoreState()

class Command(BaseCommand):
    help = 'Generate a non-editable PDF for a daily sales sheet'

    def add_arguments(self, parser):
        parser.add_argument('--branch',   type=str, help='Branch code e.g. NTB')
        parser.add_argument('--date',     type=str, help='Date YYYY-MM-DD (defaults to today)')
        parser.add_argument('--sheet-id', type=int, help='Direct sheet ID')
        parser.add_argument('--output',   type=str, help='Output file path (optional)')

    def handle(self, *args, **options):
        sheet = self._get_sheet(options)
        output_path = self._resolve_output(sheet, options.get('output'))
        self._generate_pdf(sheet, output_path)
        self.stdout.write(self.style.SUCCESS(f'PDF generated: {output_path}'))

    # ── Sheet resolution ─────────────────────────────────────────
    def _get_sheet(self, options):
        if options.get('sheet_id'):
            try:
                return DailySalesSheet.objects.get(pk=options['sheet_id'])
            except DailySalesSheet.DoesNotExist:
                raise CommandError(f"Sheet ID {options['sheet_id']} not found.")

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
                from datetime import datetime
                target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                raise CommandError('Date must be YYYY-MM-DD format.')
        else:
            target_date = timezone.localdate()

        try:
            return DailySalesSheet.objects.get(branch=branch, date=target_date)
        except DailySalesSheet.DoesNotExist:
            raise CommandError(
                f"No sheet found for {branch.name} on {target_date}."
            )

    def _resolve_output(self, sheet, custom_path):
        if custom_path:
            return custom_path
        media_root = getattr(settings, 'MEDIA_ROOT', 'media')
        sheets_dir = os.path.join(media_root, 'sheets')
        os.makedirs(sheets_dir, exist_ok=True)
        filename = f"sheet_{sheet.pk}_{sheet.date}.pdf"
        return os.path.join(sheets_dir, filename)

    # ── PDF generation ───────────────────────────────────────────
    def _generate_pdf(self, sheet, output_path):
        tmp_path = output_path.replace('.pdf', '_tmp.pdf')

        doc = SimpleDocTemplate(
            tmp_path,
            pagesize     = A4,
            leftMargin   = 20*mm,
            rightMargin  = 20*mm,
            topMargin    = 20*mm,
            bottomMargin = 22*mm,
            title        = f"Daily Sales Sheet — {sheet.branch.name} — {sheet.date}",
            author       = 'Octos — Farhat Printing Press',
            subject      = 'Daily Sales Sheet',
            creator      = 'Octos Platform',
        )

        story = []
        styles = self._build_styles()

        # ── Header ────────────────────────────────────────────────
        story += self._build_header(sheet, styles)
        story.append(Spacer(1, 6*mm))

        # ── Summary cards ──────────────────────────────────────────
        story += self._build_summary(sheet, styles)
        story.append(Spacer(1, 6*mm))

        # ── Jobs table ─────────────────────────────────────────────
        story += self._build_jobs_table(sheet, styles)
        story.append(Spacer(1, 6*mm))

        # ── Inventory consumption ───────────────────────────────────────────
        story += self._build_inventory(sheet, styles)
        story.append(Spacer(1, 6*mm))

        # ── Closing notes ──────────────────────────────────────────────────
        if sheet.notes:
            story += self._build_notes(sheet, styles)

        # ── Signature block ────────────────────────────────────────
        story += self._build_signatures(sheet, styles)

        doc.build(story, canvasmaker=NumberedCanvas)

        # ── Encrypt (read-only, no editing) ───────────────────────
        self._encrypt_pdf(tmp_path, output_path)
        os.remove(tmp_path)

    # ── Styles ───────────────────────────────────────────────────
    def _build_styles(self):
        base = getSampleStyleSheet()
        return {
            'h1': ParagraphStyle(
                'h1', fontName='Helvetica-Bold', fontSize=18,
                textColor=C_BLACK, leading=22, spaceAfter=2,
            ),
            'h2': ParagraphStyle(
                'h2', fontName='Helvetica-Bold', fontSize=11,
                textColor=C_BLACK, leading=14, spaceAfter=4,
            ),
            'h3': ParagraphStyle(
                'h3', fontName='Helvetica-Bold', fontSize=9,
                textColor=C_MID, leading=12, spaceAfter=2,
            ),
            'body': ParagraphStyle(
                'body', fontName='Helvetica', fontSize=9,
                textColor=C_MID, leading=13,
            ),
            'small': ParagraphStyle(
                'small', fontName='Helvetica', fontSize=7.5,
                textColor=C_LIGHT, leading=10,
            ),
            'label': ParagraphStyle(
                'label', fontName='Helvetica-Bold', fontSize=7,
                textColor=C_LIGHT, leading=9,
                spaceAfter=1,
            ),
            'mono': ParagraphStyle(
                'mono', fontName='Courier-Bold', fontSize=11,
                textColor=C_BLACK, leading=14,
            ),
            'mono_green': ParagraphStyle(
                'mono_green', fontName='Courier-Bold', fontSize=13,
                textColor=C_GREEN, leading=16,
            ),
            'right': ParagraphStyle(
                'right', fontName='Helvetica', fontSize=9,
                textColor=C_MID, leading=13, alignment=TA_RIGHT,
            ),
            'center': ParagraphStyle(
                'center', fontName='Helvetica', fontSize=9,
                textColor=C_MID, leading=13, alignment=TA_CENTER,
            ),
        }

    # ── Header block ─────────────────────────────────────────────
    def _build_header(self, sheet, styles):
        branch  = sheet.branch
        status  = sheet.status
        status_color = C_GREEN if status == 'CLOSED' else C_AMBER

        header_data = [
            [
                Paragraph('FARHAT PRINTING PRESS', ParagraphStyle(
                    'brand', fontName='Helvetica-Bold', fontSize=14,
                    textColor=C_BLACK, leading=17,
                )),
                Paragraph(
                    f'<font color="#{status_color.hexval()[2:]}">● {status}</font>',
                    ParagraphStyle('status', fontName='Helvetica-Bold', fontSize=9,
                                   textColor=status_color, leading=12, alignment=TA_RIGHT),
                ),
            ],
            [
                Paragraph('Daily Sales Sheet', ParagraphStyle(
                    'sub', fontName='Helvetica', fontSize=10,
                    textColor=C_LIGHT, leading=13,
                )),
                Paragraph(f'Sheet #{sheet.pk}', ParagraphStyle(
                    'sid', fontName='Courier', fontSize=8,
                    textColor=C_LIGHT, leading=11, alignment=TA_RIGHT,
                )),
            ],
        ]

        header_table = Table(header_data, colWidths=['70%', '30%'])
        header_table.setStyle(TableStyle([
            ('VALIGN',     (0,0), (-1,-1), 'MIDDLE'),
            ('BOTTOMPADDING', (0,0), (-1,-1), 2),
        ]))

        # Meta info row
        opened_by = sheet.opened_by.full_name if sheet.opened_by else '—'
        closed_by = sheet.closed_by.full_name if hasattr(sheet, 'closed_by') and sheet.closed_by else '—'

        meta_data = [
            [
                Paragraph('BRANCH',   styles['label']),
                Paragraph('DATE',     styles['label']),
                Paragraph('OPENED BY', styles['label']),
                Paragraph('CLOSED BY', styles['label']),
                Paragraph('GENERATED', styles['label']),
            ],
            [
                Paragraph(branch.name,                                    styles['body']),
                Paragraph(str(sheet.date),                                styles['body']),
                Paragraph(opened_by,                                      styles['body']),
                Paragraph(closed_by,                                      styles['body']),
                Paragraph(timezone.now().strftime('%d %b %Y %H:%M'),      styles['body']),
            ],
        ]

        meta_table = Table(meta_data, colWidths=['20%', '16%', '22%', '22%', '20%'])
        meta_table.setStyle(TableStyle([
            ('BACKGROUND',    (0,0), (-1,0), C_BG),
            ('BACKGROUND',    (0,1), (-1,1), white),
            ('BOX',           (0,0), (-1,-1), 0.5, C_BORDER),
            ('INNERGRID',     (0,0), (-1,-1), 0.3, C_BORDER),
            ('TOPPADDING',    (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ('LEFTPADDING',   (0,0), (-1,-1), 6),
        ]))

        return [
            header_table,
            Spacer(1, 4*mm),
            HRFlowable(width='100%', thickness=0.5, color=C_BORDER),
            Spacer(1, 3*mm),
            meta_table,
        ]

    # ── Summary cards ─────────────────────────────────────────────
    def _build_summary(self, sheet, styles):
        def _fmt(val):
            return f"GHS {Decimal(val or 0):,.2f}"

        total = (
            Decimal(sheet.total_cash or 0) +
            Decimal(sheet.total_momo or 0) +
            Decimal(sheet.total_pos  or 0)
        )

        cards = [
            ('CASH',          _fmt(sheet.total_cash), C_GREEN,  C_GREEN_BG),
            ('MOMO',          _fmt(sheet.total_momo), C_AMBER,  C_AMBER_BG),
            ('POS',           _fmt(sheet.total_pos),  C_BLUE,   C_BLUE_BG),
            ('TOTAL COLLECTED', _fmt(total),          C_BLACK,  C_BG),
        ]

        card_data = [[
            Table(
                [
                    [Paragraph(label, ParagraphStyle(
                        'cl', fontName='Helvetica-Bold', fontSize=7,
                        textColor=color, leading=9,
                    ))],
                    [Paragraph(amount, ParagraphStyle(
                        'ca', fontName='Courier-Bold', fontSize=13,
                        textColor=color, leading=16,
                    ))],
                ],
                colWidths=['100%'],
            )
            for label, amount, color, bg in cards
        ]]

        summary_table = Table(card_data, colWidths=['25%', '25%', '25%', '25%'])
        summary_table.setStyle(TableStyle([
            ('BACKGROUND',    (0,0), (0,0), C_GREEN_BG),
            ('BACKGROUND',    (1,0), (1,0), C_AMBER_BG),
            ('BACKGROUND',    (2,0), (2,0), C_BLUE_BG),
            ('BACKGROUND',    (3,0), (3,0), C_BG),
            ('BOX',           (0,0), (-1,-1), 0.5, C_BORDER),
            ('INNERGRID',     (0,0), (-1,-1), 0.3, C_BORDER),
            ('TOPPADDING',    (0,0), (-1,-1), 6),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
            ('LEFTPADDING',   (0,0), (-1,-1), 8),
        ]))

        section_title = Paragraph('COLLECTION SUMMARY', ParagraphStyle(
            'st', fontName='Helvetica-Bold', fontSize=8,
            textColor=C_LIGHT, leading=10, spaceAfter=4,
        ))

        return [section_title, summary_table]

    # ── Jobs table ───────────────────────────────────────────────
    def _build_jobs_table(self, sheet, styles):
        jobs = Job.objects.filter(
            daily_sheet=sheet,
        ).select_related('customer', 'intake_by').order_by('created_at')

        section_title = Paragraph(
            f'JOBS ({jobs.count()} total)',
            ParagraphStyle('st', fontName='Helvetica-Bold', fontSize=8,
                           textColor=C_LIGHT, leading=10, spaceAfter=4),
        )

        if not jobs.exists():
            return [
                section_title,
                Paragraph('No jobs recorded on this sheet.', styles['body']),
            ]

        col_labels = ['#', 'JOB REF', 'TITLE', 'TYPE', 'STATUS',
                      'PAYMENT', 'AMOUNT PAID', 'CREATED']

        rows = [col_labels]

        for i, job in enumerate(jobs, 1):
            amount = f"GHS {Decimal(job.amount_paid or 0):,.2f}"
            rows.append([
                str(i),
                job.job_number or f'#{job.pk}',
                (job.title or '—')[:35],
                job.job_type,
                job.status.replace('_', ' '),
                job.payment_method or '—',
                amount,
                job.created_at.strftime('%H:%M') if job.created_at else '—',
            ])

        col_widths = [8*mm, 35*mm, 55*mm, 20*mm, 28*mm, 18*mm, 28*mm, 14*mm]

        table = Table(rows, colWidths=col_widths, repeatRows=1)
        table.setStyle(TableStyle([
            # Header row
            ('BACKGROUND',    (0,0), (-1,0), C_BLACK),
            ('TEXTCOLOR',     (0,0), (-1,0), C_WHITE),
            ('FONTNAME',      (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE',      (0,0), (-1,0), 7),
            ('TOPPADDING',    (0,0), (-1,0), 5),
            ('BOTTOMPADDING', (0,0), (-1,0), 5),
            ('LEFTPADDING',   (0,0), (-1,-1), 5),
            # Body rows
            ('FONTNAME',      (0,1), (-1,-1), 'Helvetica'),
            ('FONTSIZE',      (0,1), (-1,-1), 7.5),
            ('TOPPADDING',    (0,1), (-1,-1), 4),
            ('BOTTOMPADDING', (0,1), (-1,-1), 4),
            ('ROWBACKGROUNDS',(0,1), (-1,-1), [white, C_BG]),
            ('GRID',          (0,0), (-1,-1), 0.3, C_BORDER),
            ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
            # Amount column right-aligned
            ('ALIGNMENT',     (6,0), (6,-1), 'RIGHT'),
            ('ALIGNMENT',     (0,0), (0,-1), 'CENTER'),
        ]))

        return [section_title, table]
    
    # ── Inventory consumption ─────────────────────────────────────────────────
    def _build_inventory(self, sheet, styles):
        from apps.inventory.inventory_engine import InventoryEngine

        title = Paragraph('INVENTORY CONSUMED TODAY', ParagraphStyle(
            'it', fontName='Helvetica-Bold', fontSize=8,
            textColor=C_LIGHT, leading=10, spaceAfter=4,
        ))

        try:
            engine   = InventoryEngine(sheet.branch)
            snapshot = engine.generate_daily_snapshot(sheet.date)
            items    = snapshot.get('items', [])
        except Exception:
            items = []

        if not items:
            return [
                title,
                Paragraph('No inventory movements recorded for this day.', styles['body']),
                Spacer(1, 4*mm),
            ]

        headers = ['CONSUMABLE', 'CATEGORY', 'UNIT', 'CONSUMED', 'CLOSING', 'STATUS']
        rows    = [headers]

        for item in items:
            is_low      = item.get('is_low', False)
            closing     = item.get('closing', 0)
            consumed    = item.get('consumed', 0)
            unit        = item.get('unit', '')
            status_text = 'LOW' if is_low else 'OK'
            rows.append([
                item.get('consumable', '—'),
                item.get('category',  '—'),
                unit,
                f"{consumed}",
                f"{closing} {unit}",
                status_text,
            ])

        col_widths = [55*mm, 30*mm, 18*mm, 22*mm, 28*mm, 14*mm]
        table = Table(rows, colWidths=col_widths, repeatRows=1)

        # Build row styles — highlight LOW rows in red
        row_styles = [
            ('BACKGROUND',    (0,0), (-1,0), C_BLACK),
            ('TEXTCOLOR',     (0,0), (-1,0), C_WHITE),
            ('FONTNAME',      (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE',      (0,0), (-1,0), 7),
            ('TOPPADDING',    (0,0), (-1,0), 5),
            ('BOTTOMPADDING', (0,0), (-1,0), 5),
            ('LEFTPADDING',   (0,0), (-1,-1), 5),
            ('FONTNAME',      (0,1), (-1,-1), 'Helvetica'),
            ('FONTSIZE',      (0,1), (-1,-1), 7.5),
            ('TOPPADDING',    (0,1), (-1,-1), 4),
            ('BOTTOMPADDING', (0,1), (-1,-1), 4),
            ('ROWBACKGROUNDS',(0,1), (-1,-1), [white, C_BG]),
            ('GRID',          (0,0), (-1,-1), 0.3, C_BORDER),
            ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
            ('ALIGNMENT',     (3,0), (4,-1), 'RIGHT'),
            ('ALIGNMENT',     (5,0), (5,-1), 'CENTER'),
        ]

        for i, item in enumerate(items, start=1):
            if item.get('is_low', False):
                row_styles.append(('TEXTCOLOR', (5,i), (5,i), C_RED))
                row_styles.append(('FONTNAME',  (5,i), (5,i), 'Helvetica-Bold'))
                row_styles.append(('TEXTCOLOR', (4,i), (4,i), C_RED))

        table.setStyle(TableStyle(row_styles))

        return [title, table, Spacer(1, 4*mm)]

    # ── Notes block ──────────────────────────────────────────────
    def _build_notes(self, sheet, styles):
        title = Paragraph('CLOSING NOTES', ParagraphStyle(
            'nt', fontName='Helvetica-Bold', fontSize=8,
            textColor=C_LIGHT, leading=10, spaceAfter=4,
        ))
        notes = Paragraph(sheet.notes or '—', styles['body'])
        box = Table([[notes]], colWidths=['100%'])
        box.setStyle(TableStyle([
            ('BOX',           (0,0), (-1,-1), 0.5, C_BORDER),
            ('BACKGROUND',    (0,0), (-1,-1), C_BG),
            ('TOPPADDING',    (0,0), (-1,-1), 6),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
            ('LEFTPADDING',   (0,0), (-1,-1), 8),
        ]))
        return [title, box, Spacer(1, 4*mm)]

    # ── Signature block ──────────────────────────────────────────
    def _build_signatures(self, sheet, styles):
        title = Paragraph('AUTHORISATION', ParagraphStyle(
            'at', fontName='Helvetica-Bold', fontSize=8,
            textColor=C_LIGHT, leading=10, spaceAfter=8,
        ))

        sig_data = [[
            Table([
                [Paragraph('Branch Manager', styles['label'])],
                [Spacer(1, 12*mm)],
                [HRFlowable(width='80%', thickness=0.5, color=C_BORDER)],
                [Paragraph('Signature & Date', styles['small'])],
            ], colWidths=['100%']),
            Table([
                [Paragraph('Cashier', styles['label'])],
                [Spacer(1, 12*mm)],
                [HRFlowable(width='80%', thickness=0.5, color=C_BORDER)],
                [Paragraph('Signature & Date', styles['small'])],
            ], colWidths=['100%']),
            Table([
                [Paragraph('Reviewed By', styles['label'])],
                [Spacer(1, 12*mm)],
                [HRFlowable(width='80%', thickness=0.5, color=C_BORDER)],
                [Paragraph('Signature & Date', styles['small'])],
            ], colWidths=['100%']),
        ]]

        sig_table = Table(sig_data, colWidths=['33%', '33%', '34%'])
        sig_table.setStyle(TableStyle([
            ('VALIGN',     (0,0), (-1,-1), 'TOP'),
            ('LEFTPADDING',(0,0), (-1,-1), 0),
        ]))

        return [
            HRFlowable(width='100%', thickness=0.5, color=C_BORDER),
            Spacer(1, 4*mm),
            title,
            sig_table,
        ]

    # ── Encrypt PDF (read-only) ───────────────────────────────────
    def _encrypt_pdf(self, input_path, output_path):
        reader = PdfReader(input_path)
        writer = PdfWriter()

        for page in reader.pages:
            writer.add_page(page)

        # Owner password allows printing but blocks editing
        writer.encrypt(
            user_password  = '',
            owner_password = 'octos-sheet-readonly',
            use_128bit     = True,
        )

        with open(output_path, 'wb') as f:
            writer.write(f)