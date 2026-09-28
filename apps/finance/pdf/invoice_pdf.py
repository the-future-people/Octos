# apps/finance/pdf/invoice_pdf.py
"""
The invoice PDF.

Moved out of finance/api/views.py. The builder imports reportlab inside
itself, which is left as it was — this move changes where the code
lives, nothing about how it runs.
"""


def _generate_invoice_pdf(invoice):
    """Generate a PDF for the invoice and save path to invoice.pdf_path."""
    import os, base64, io
    from django.conf import settings

    media_root   = getattr(settings, 'MEDIA_ROOT', 'media')
    invoices_dir = os.path.join(media_root, 'invoices')
    os.makedirs(invoices_dir, exist_ok=True)
    output_path  = os.path.join(invoices_dir, f"{invoice.invoice_number}.pdf")

    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle,
        Paragraph, Spacer, HRFlowable, Image,
    )
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT

    FARHAT_RED  = colors.HexColor('#E31E24')
    CHARCOAL    = colors.HexColor('#1A1A1A')
    DARK_GREY   = colors.HexColor('#444444')
    MID_GREY    = colors.HexColor('#777777')
    LIGHT_GREY  = colors.HexColor('#F0F0F0')
    WHITE       = colors.white

    PAGE_W, PAGE_H = A4
    LM = RM = 20 * mm
    CONTENT_W = PAGE_W - LM - RM

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=RM, leftMargin=LM,
        topMargin=0,    bottomMargin=20*mm,
    )

    def fmt(n):
        return f"GHS {float(n or 0):,.2f}"

    def style(name, **kw):
        return ParagraphStyle(name, **kw)

    sm        = style('sm',  fontSize=9,  fontName='Helvetica',      textColor=DARK_GREY)
    sm_bold   = style('smb', fontSize=9,  fontName='Helvetica-Bold', textColor=CHARCOAL)
    lbl       = style('lbl', fontSize=8,  fontName='Helvetica-Bold', textColor=colors.HexColor('#999999'), leading=10)
    right_sm  = style('rsm', fontSize=9,  fontName='Helvetica',      textColor=DARK_GREY,  alignment=TA_RIGHT)
    right_b   = style('rb',  fontSize=13, fontName='Helvetica-Bold', textColor=FARHAT_RED, alignment=TA_RIGHT)
    right_m   = style('rm',  fontSize=9,  fontName='Helvetica-Bold', textColor=CHARCOAL,   alignment=TA_RIGHT)
    center_sm = style('csm', fontSize=9,  fontName='Helvetica',      textColor=DARK_GREY,  alignment=TA_CENTER)
    total_lbl = style('tl',  fontSize=11, fontName='Helvetica-Bold', textColor=CHARCOAL)
    total_amt = style('ta',  fontSize=11, fontName='Helvetica-Bold', textColor=FARHAT_RED, alignment=TA_RIGHT)
    footer_sm = style('ft',  fontSize=8,  fontName='Helvetica',      textColor=MID_GREY,   alignment=TA_CENTER)

    story = []

    # -- Logo image from base64
    from apps.core.branding import LOGO_B64
    logo_bytes = base64.b64decode(LOGO_B64)
    logo_img   = Image(io.BytesIO(logo_bytes), width=14*mm, height=14*mm)

    # -- Header: red bar spanning full page width
    company_cell = [
        Paragraph('<font color="#FFFFFF"><b>Farhat Printing Press</b></font>',
                  style('co', fontSize=16, fontName='Helvetica-Bold',
                        textColor=WHITE, leading=20)),
        Paragraph('<font color="#FFFFFF">Professional Printing Services</font>',
                  style('cs', fontSize=8, fontName='Helvetica',
                        textColor=colors.HexColor('#FFAAAA'), leading=11)),
    ]
    invoice_type_color = '#FFFFFF'
    type_cell = Paragraph(
        f'<font color="#FFFFFF"><b>{invoice.invoice_type} INVOICE</b></font>',
        style('it', fontSize=11, fontName='Helvetica-Bold',
              textColor=WHITE, alignment=TA_RIGHT, leading=14),
    )

    header_data = [[ logo_img, company_cell, type_cell ]]
    header_table = Table(header_data, colWidths=[18*mm, CONTENT_W - 18*mm - 38*mm, 38*mm])
    header_table.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,-1), FARHAT_RED),
        ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
        ('LEFTPADDING',   (0,0), (0,0),   4),
        ('LEFTPADDING',   (1,0), (1,0),   8),
        ('RIGHTPADDING',  (2,0), (2,0),   8),
        ('TOPPADDING',    (0,0), (-1,-1), 10),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
    ]))
    story.append(header_table)

    # -- Branch info bar: centered pipe-separated text
    branch = invoice.branch
    branch_parts = [branch.name]
    if branch.phone or branch.whatsapp_number:
        branch_parts.append(branch.phone or branch.whatsapp_number)
    if branch.email:
        branch_parts.append(branch.email)
    branch_line = '  |  '.join(branch_parts)

    branch_bar_data = [[ Paragraph(branch_line,
        style('bb', fontSize=8.5, fontName='Helvetica',
              textColor=DARK_GREY, alignment=TA_CENTER)) ]]
    branch_bar = Table(branch_bar_data, colWidths=[CONTENT_W])
    branch_bar.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,-1), colors.HexColor('#FAFAFA')),
        ('TOPPADDING',    (0,0), (-1,-1), 7),
        ('BOTTOMPADDING', (0,0), (-1,-1), 7),
        ('LINEBELOW',     (0,0), (-1,-1), 0.5, LIGHT_GREY),
    ]))
    story.append(branch_bar)
    story.append(Spacer(1, 6*mm))

    # -- Bill To + Invoice meta two-column
    issued = invoice.issue_date.strftime('%d %b %Y') if invoice.issue_date else '-'
    due    = invoice.due_date.strftime('%d %b %Y')   if invoice.due_date   else '-'

    primary   = invoice.bill_to_company or invoice.bill_to_name
    secondary = invoice.bill_to_name if invoice.bill_to_company else None
    bill_lines = [Paragraph('BILL TO', lbl)]
    bill_lines.append(Paragraph(primary,
        style('bp', fontSize=12, fontName='Helvetica-Bold', textColor=CHARCOAL)))
    if secondary:
        bill_lines.append(Paragraph(secondary, sm_bold))
    if invoice.bill_to_phone:
        bill_lines.append(Paragraph(invoice.bill_to_phone, sm))
    if invoice.bill_to_email:
        bill_lines.append(Paragraph(invoice.bill_to_email, sm))

    meta_lines = [
        Paragraph('INVOICE NO', lbl),
        Paragraph(invoice.invoice_number,
            style('inv', fontSize=13, fontName='Helvetica-Bold',
                  textColor=FARHAT_RED, alignment=TA_RIGHT)),
        Spacer(1, 4),
        Paragraph('DATE ISSUED', lbl),
        Paragraph(issued, right_m),
        Spacer(1, 4),
        Paragraph('DUE DATE', lbl),
        Paragraph(due, right_m),
    ]

    meta_table = Table([[bill_lines, meta_lines]], colWidths=[CONTENT_W*0.55, CONTENT_W*0.45])
    meta_table.setStyle(TableStyle([
        ('VALIGN',       (0,0), (-1,-1), 'TOP'),
        ('LINEBEFORE',   (0,0), (0,-1),  2, FARHAT_RED),
        ('LEFTPADDING',  (0,0), (0,-1),  10),
        ('LEFTPADDING',  (1,0), (1,-1),  0),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 6*mm))

    # -- Job ref
    if invoice.job:
        story.append(Paragraph(
            f"Job Reference: <b>{invoice.job.job_number}</b>", sm))
        story.append(Spacer(1, 3*mm))

    # -- Line items table
    th = style('th', fontSize=9, fontName='Helvetica-Bold',
               textColor=WHITE)
    th_r = style('thr', fontSize=9, fontName='Helvetica-Bold',
                 textColor=WHITE, alignment=TA_RIGHT)
    th_c = style('thc', fontSize=9, fontName='Helvetica-Bold',
                 textColor=WHITE, alignment=TA_CENTER)

    table_data = [[
        Paragraph('SERVICE', th),
        Paragraph('QTY', th_c),
        Paragraph('UNIT PRICE', th_r),
        Paragraph('TOTAL', th_r),
    ]]

    for li in invoice.line_items.all():
        detail = f"{li.paper_size} &middot; {'Colour' if li.is_color else 'B&amp;W'}"
        if li.pages > 1:
            detail += f" &middot; {li.pages}pp &times; {li.sets} sets"
        table_data.append([
            [Paragraph(li.label, sm_bold), Paragraph(detail, sm)],
            Paragraph(str(li.quantity),
                style('qc', fontSize=9, fontName='Helvetica',
                      textColor=CHARCOAL, alignment=TA_CENTER)),
            Paragraph(fmt(li.unit_price),
                style('up', fontSize=9, fontName='Helvetica',
                      textColor=DARK_GREY, alignment=TA_RIGHT)),
            Paragraph(fmt(li.line_total),
                style('lt', fontSize=9, fontName='Helvetica-Bold',
                      textColor=CHARCOAL, alignment=TA_RIGHT)),
        ])

    col_w = [CONTENT_W*0.50, CONTENT_W*0.10, CONTENT_W*0.20, CONTENT_W*0.20]
    items_table = Table(table_data, colWidths=col_w, repeatRows=1)
    items_table.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,0),  FARHAT_RED),
        ('ROWBACKGROUNDS',(0,1), (-1,-1), [WHITE, colors.HexColor('#FAFAFA')]),
        ('LINEBELOW',     (0,0), (-1,-1), 0.5, LIGHT_GREY),
        ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING',    (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('LEFTPADDING',   (0,0), (-1,-1), 8),
        ('RIGHTPADDING',  (0,0), (-1,-1), 8),
    ]))
    story.append(items_table)
    story.append(Spacer(1, 4*mm))

    # -- Totals
    totals_data = [[
        Paragraph('Subtotal', sm),
        Paragraph(fmt(invoice.subtotal), right_sm),
    ]]
    if invoice.vat_rate:
        totals_data.append([
            Paragraph(f'VAT ({invoice.vat_rate}%)', sm),
            Paragraph(fmt(invoice.vat_amount), right_sm),
        ])
    totals_data.append([
        Paragraph('<b>Total</b>', total_lbl),
        Paragraph(f'<b>{fmt(invoice.total)}</b>', total_amt),
    ])

    totals_table = Table(totals_data, colWidths=[CONTENT_W*0.75, CONTENT_W*0.25])
    totals_table.setStyle(TableStyle([
        ('ALIGN',         (1,0),  (1,-1),  'RIGHT'),
        ('LINEABOVE',     (0,-1), (-1,-1), 1.5, FARHAT_RED),
        ('LINEBELOW',     (0,0),  (-1,-2), 0.5, LIGHT_GREY),
        ('TOPPADDING',    (0,0),  (-1,-1), 5),
        ('BOTTOMPADDING', (0,0),  (-1,-1), 5),
    ]))
    story.append(totals_table)

    # -- BM note
    if invoice.bm_note:
        story.append(Spacer(1, 5*mm))
        story.append(HRFlowable(width=CONTENT_W, thickness=0.5,
                                color=LIGHT_GREY))
        story.append(Spacer(1, 3*mm))
        story.append(Paragraph(invoice.bm_note, sm))

    # -- Footer
    story.append(Spacer(1, 8*mm))
    footer_data = [[
        Paragraph(
            'Thank you for choosing Farhat Printing Press',
            style('fl', fontSize=8, fontName='Helvetica',
                  textColor=WHITE, alignment=TA_LEFT)),
        Paragraph(
            'FARHAT &trade;',
            style('fr', fontSize=9, fontName='Helvetica-Bold',
                  textColor=FARHAT_RED, alignment=TA_RIGHT)),
    ]]
    footer_table = Table(footer_data, colWidths=[CONTENT_W*0.7, CONTENT_W*0.3])
    footer_table.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,-1), CHARCOAL),
        ('TOPPADDING',    (0,0), (-1,-1), 10),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
        ('LEFTPADDING',   (0,0), (0,-1),  14),
        ('RIGHTPADDING',  (-1,0),(-1,-1), 14),
        ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
    ]))
    story.append(footer_table)

    doc.build(story)

    invoice.pdf_path = output_path
    invoice.save(update_fields=['pdf_path', 'updated_at'])

