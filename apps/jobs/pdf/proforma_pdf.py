"""
Proforma PDF.

Returns bytes rather than writing to disk. MEDIA_ROOT is an ephemeral
container filesystem, so a stored file is destroyed on the next deploy —
the invoice generator survives that only because it silently regenerates
on every download. A proforma is fully derivable from its stored lines, so
there is no reason to keep a file at all.

House style follows the invoice: Farhat red, the same mark, the same
table treatment.
"""

import base64
import io

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from apps.core.branding import LOGO_B64

FARHAT_RED = colors.HexColor('#E31E24')
CHARCOAL   = colors.HexColor('#1A1A1A')
DARK_GREY  = colors.HexColor('#444444')
MID_GREY   = colors.HexColor('#777777')
PALE_GREY  = colors.HexColor('#F0F0F0')
WHITE      = colors.white


def _style(name, **kw):
    return ParagraphStyle(name, **kw)


def _fmt(n):
    return f"GHS {float(n or 0):,.2f}"


def _spec_line(li):
    """
    The human description under a service name. Built only from fields that
    apply — the invoice prints 'A4 · B&W' against a binding, which is wrong
    on both counts and reads as carelessness on a customer-facing document.
    """
    bits = []
    if li.get('ring_size'):
        bits.append(f"{li['ring_size']}mm ring")
    if li.get('output_mode'):
        bits.append(li['output_mode'].replace('_', ' + ').title())
    if not li.get('ring_size'):
        pages = int(li.get('pages') or 1)
        if pages > 1:
            bits.append(f"{pages}pp")
        if li.get('is_color'):
            bits.append('Colour')
    return ' · '.join(bits)


def build_proforma_pdf(proforma) -> bytes:
    """Render the proforma and return the PDF as bytes."""
    branch = proforma.branch
    buf    = io.BytesIO()

    PAGE_W, _ = A4
    LM = RM = 20 * mm
    CONTENT_W = PAGE_W - LM - RM

    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=LM, rightMargin=RM,
        topMargin=0, bottomMargin=18 * mm,
        title=proforma.proforma_number,
    )

    sm       = _style('sm',  fontSize=9,  fontName='Helvetica',      textColor=DARK_GREY)
    sm_bold  = _style('smb', fontSize=10, fontName='Helvetica-Bold', textColor=CHARCOAL)
    lbl      = _style('lbl', fontSize=7,  fontName='Helvetica-Bold',
                      textColor=colors.HexColor('#999999'), leading=10)
    right_sm = _style('rsm', fontSize=9,  fontName='Helvetica-Bold',
                      textColor=CHARCOAL, alignment=TA_RIGHT)
    right_no = _style('rno', fontSize=13, fontName='Helvetica-Bold',
                      textColor=FARHAT_RED, alignment=TA_RIGHT)
    cell     = _style('cel', fontSize=9,  fontName='Helvetica-Bold', textColor=CHARCOAL)
    cell_sub = _style('csb', fontSize=8,  fontName='Helvetica',      textColor=MID_GREY)
    foot     = _style('ft',  fontSize=8,  fontName='Helvetica',
                      textColor=MID_GREY, alignment=TA_CENTER, leading=12)
    foot_b   = _style('ftb', fontSize=8,  fontName='Helvetica-Bold',
                      textColor=DARK_GREY, alignment=TA_CENTER, leading=12)

    story = []

    # ── Red header band ──────────────────────────────────────────
    logo = Image(io.BytesIO(base64.b64decode(LOGO_B64)), width=14 * mm, height=14 * mm)

    header = Table(
        [[
            logo,
            [
                Paragraph('<font color="#FFFFFF"><b>Farhat Printing Press</b></font>',
                          _style('co', fontSize=16, fontName='Helvetica-Bold',
                                 textColor=WHITE, leading=20)),
                Paragraph('<font color="#FFAAAA">Professional Printing Services</font>',
                          _style('cs', fontSize=8, textColor=colors.HexColor('#FFAAAA'),
                                 leading=11)),
            ],
            Paragraph('<font color="#FFFFFF"><b>PROFORMA INVOICE</b></font>',
                      _style('ty', fontSize=11, fontName='Helvetica-Bold',
                             textColor=WHITE, alignment=TA_RIGHT, leading=14)),
        ]],
        colWidths=[18 * mm, CONTENT_W - 78 * mm, 60 * mm],
    )
    header.setStyle(TableStyle([
        ('BACKGROUND',   (0, 0), (-1, -1), FARHAT_RED),
        ('VALIGN',       (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING',  (0, 0), (0, 0), 6),
        ('TOPPADDING',   (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 10),
    ]))
    story.append(header)

    contact = ' | '.join(filter(None, [
        branch.name, branch.phone or '', branch.email or '',
    ]))
    strip = Table([[Paragraph(contact, _style('ct', fontSize=8, textColor=DARK_GREY,
                                              alignment=TA_CENTER))]],
                  colWidths=[CONTENT_W])
    strip.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), PALE_GREY),
        ('TOPPADDING',    (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(strip)
    story.append(Spacer(1, 8 * mm))

    # ── Bill to / document meta ──────────────────────────────────
    bill = [Paragraph('QUOTATION FOR', lbl),
            Paragraph(proforma.issued_to, sm_bold)]
    if proforma.contact_person:
        bill.append(Paragraph(proforma.contact_person, sm))
    if proforma.contact_phone:
        bill.append(Paragraph(proforma.contact_phone, sm))
    if proforma.contact_email:
        bill.append(Paragraph(proforma.contact_email, sm))

    issued = proforma.issued_at or proforma.created_at
    meta = [
        Paragraph('PROFORMA NO', _style('l1', parent=lbl, alignment=TA_RIGHT)),
        Paragraph(proforma.proforma_number, right_no),
        Spacer(1, 3 * mm),
        Paragraph('DATE ISSUED', _style('l2', parent=lbl, alignment=TA_RIGHT)),
        Paragraph(issued.strftime('%d %b %Y'), right_sm),
        Spacer(1, 2 * mm),
        Paragraph('VALID UNTIL', _style('l3', parent=lbl, alignment=TA_RIGHT)),
        Paragraph(proforma.valid_until.strftime('%d %b %Y'), right_sm),
    ]

    meta_table = Table([[bill, meta]], colWidths=[CONTENT_W * 0.55, CONTENT_W * 0.45])
    meta_table.setStyle(TableStyle([
        ('VALIGN',      (0, 0), (-1, -1), 'TOP'),
        ('LINEBEFORE',  (0, 0), (0, 0), 2, FARHAT_RED),
        ('LEFTPADDING', (0, 0), (0, 0), 8),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 8 * mm))

    # ── Lines ────────────────────────────────────────────────────
    rows = [[
        Paragraph('<font color="#FFFFFF"><b>SERVICE</b></font>',
                  _style('h1', fontSize=8, fontName='Helvetica-Bold', textColor=WHITE)),
        Paragraph('<font color="#FFFFFF"><b>QTY</b></font>',
                  _style('h2', fontSize=8, fontName='Helvetica-Bold',
                         textColor=WHITE, alignment=TA_CENTER)),
        Paragraph('<font color="#FFFFFF"><b>UNIT PRICE</b></font>',
                  _style('h3', fontSize=8, fontName='Helvetica-Bold',
                         textColor=WHITE, alignment=TA_RIGHT)),
        Paragraph('<font color="#FFFFFF"><b>TOTAL</b></font>',
                  _style('h4', fontSize=8, fontName='Helvetica-Bold',
                         textColor=WHITE, alignment=TA_RIGHT)),
    ]]

    for li in proforma.line_items:
        spec = _spec_line(li)
        name_cell = [Paragraph(li['service_name'], cell)]
        if spec:
            name_cell.append(Paragraph(spec, cell_sub))
        rows.append([
            name_cell,
            Paragraph(str(li['quantity']),
                      _style('q', fontSize=9, textColor=DARK_GREY, alignment=TA_CENTER)),
            Paragraph(_fmt(li['unit_price']),
                      _style('u', fontSize=9, textColor=DARK_GREY, alignment=TA_RIGHT)),
            Paragraph(_fmt(li['total']),
                      _style('t', fontSize=9, fontName='Helvetica-Bold',
                             textColor=CHARCOAL, alignment=TA_RIGHT)),
        ])

    tbl = Table(rows, colWidths=[CONTENT_W - 90 * mm, 20 * mm, 35 * mm, 35 * mm],
                repeatRows=1)
    tbl.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, 0), FARHAT_RED),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING',    (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
        ('LEFTPADDING',   (0, 0), (0, -1), 8),
        ('RIGHTPADDING',  (-1, 0), (-1, -1), 8),
        ('LINEBELOW',     (0, 1), (-1, -1), 0.5, colors.HexColor('#EFEDEA')),
        ('ROWBACKGROUNDS',(0, 1), (-1, -1), [WHITE, colors.HexColor('#FAFAF9')]),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 6 * mm))

    # ── Totals ───────────────────────────────────────────────────
    totals = Table(
        [
            [Paragraph('Subtotal', sm),
             Paragraph(_fmt(proforma.subtotal), _style('s', parent=sm, alignment=TA_RIGHT))],
            [Paragraph('<b>Total</b>',
                       _style('tl', fontSize=11, fontName='Helvetica-Bold', textColor=CHARCOAL)),
             Paragraph(f'<b>{_fmt(proforma.total)}</b>',
                       _style('ta', fontSize=11, fontName='Helvetica-Bold',
                              textColor=FARHAT_RED, alignment=TA_RIGHT))],
        ],
        colWidths=[45 * mm, 45 * mm],
        hAlign='RIGHT',
    )
    totals.setStyle(TableStyle([
        ('LINEABOVE',     (0, 1), (-1, 1), 0.8, colors.HexColor('#DAD8D4')),
        ('TOPPADDING',    (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(totals)

    if proforma.notes:
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph(proforma.notes, sm))

    # ── Footer ───────────────────────────────────────────────────
    story.append(Spacer(1, 12 * mm))
    story.append(Paragraph(
        f"This quotation is valid until "
        f"{proforma.valid_until.strftime('%d %b %Y')}. "
        f"Prices are subject to change after this date.",
        foot_b,
    ))
    story.append(Paragraph(
        "To proceed, please contact us to confirm.", foot,
    ))
    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph("Kindly make payment to", foot))
    story.append(Paragraph("Mobile Money: 0556244194", foot_b))
    story.append(Paragraph("Account Name: Adjei Kingsford", foot_b))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(
        "Thank you for choosing Farhat Printing Press&nbsp;&nbsp;FARHAT &#8482;", foot,
    ))

    doc.build(story)
    return buf.getvalue()