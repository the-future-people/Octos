"""
Quote PDF (25 Nov 2026).

What staff send with a quote from the inbox, when "Attach the quote as a
PDF" is ticked: the order's lines exactly as priced, the total, when it
will be ready and how to pay. Something a customer can save, print or
forward to whoever pays.

Not a proforma: no validity, no number of its own, nothing to convert. It
is the order (ORD-…) on paper. A customer who needs a formal document for
approval gets a proforma instead. House style follows the proforma.

Returns bytes, like the proforma: the order holds everything it shows.
"""

import base64
import io
from decimal import Decimal

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.core.branding import LOGO_B64
from apps.jobs.pdf.proforma_pdf import (
    CHARCOAL, DARK_GREY, FARHAT_RED, MID_GREY, PALE_GREY, WHITE, _fmt, _style,
)


def _spec(line):
    """'4 pages' under a printing line; nothing where pages mean nothing."""
    pages = (line.get('specifications') or {}).get('pages')
    try:
        pages = int(pages or 0)
    except (TypeError, ValueError):
        pages = 0
    return f'{pages} pages a copy' if pages > 1 else ('1 page a copy' if pages == 1 else '')


def build_quote_pdf(order, name='', phone='', ready='', code='', how='link') -> bytes:
    """
    The order as a one-page quote. ready is the words staff saw ("about
    3:40pm today"); code is the pickup code when it pays at the counter.
    """
    buf = io.BytesIO()
    page_w, _ = A4
    lm = rm = 20 * mm
    width = page_w - lm - rm
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=lm, rightMargin=rm, topMargin=0,
                            bottomMargin=18 * mm, title=f'Quote {order.order_number}')

    sm = _style('qsm', fontSize=9, fontName='Helvetica', textColor=DARK_GREY)
    bold = _style('qb', fontSize=10, fontName='Helvetica-Bold', textColor=CHARCOAL)
    label = _style('ql', fontSize=7, fontName='Helvetica-Bold', textColor=colors.HexColor('#999999'), leading=10)
    right = _style('qr', fontSize=9, fontName='Helvetica-Bold', textColor=CHARCOAL, alignment=TA_RIGHT)
    number = _style('qn', fontSize=13, fontName='Helvetica-Bold', textColor=FARHAT_RED, alignment=TA_RIGHT)
    cell = _style('qc', fontSize=9, fontName='Helvetica-Bold', textColor=CHARCOAL)
    sub = _style('qs', fontSize=8, fontName='Helvetica', textColor=MID_GREY)
    foot = _style('qf', fontSize=8.5, fontName='Helvetica', textColor=MID_GREY, alignment=TA_CENTER, leading=13)
    foot_b = _style('qfb', fontSize=9, fontName='Helvetica-Bold', textColor=DARK_GREY, alignment=TA_CENTER,
                    leading=13)
    head = _style('qh', fontSize=8, fontName='Helvetica-Bold', textColor=WHITE)

    story = []
    logo = Image(io.BytesIO(base64.b64decode(LOGO_B64)), width=14 * mm, height=14 * mm)
    band = Table([[
        logo,
        [Paragraph('<b>Farhat Printing Press</b>',
                   _style('qco', fontSize=16, fontName='Helvetica-Bold', textColor=WHITE, leading=20)),
         Paragraph('Professional Printing Services',
                   _style('qcs', fontSize=8, textColor=colors.HexColor('#FFAAAA'), leading=11))],
        Paragraph('<b>QUOTE</b>', _style('qty', fontSize=11, fontName='Helvetica-Bold', textColor=WHITE,
                                         alignment=TA_RIGHT, leading=14)),
    ]], colWidths=[18 * mm, width - 78 * mm, 60 * mm])
    band.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), FARHAT_RED), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (0, 0), 6), ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
    ]))
    story.append(band)

    branch = order.branch
    contact = ' | '.join(filter(None, [getattr(branch, 'name', ''), getattr(branch, 'phone', '') or '',
                                       getattr(branch, 'email', '') or '']))
    strip = Table([[Paragraph(contact, _style('qct', fontSize=8, textColor=DARK_GREY, alignment=TA_CENTER))]],
                  colWidths=[width])
    strip.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), PALE_GREY),
                               ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5)]))
    story += [strip, Spacer(1, 8 * mm)]

    made = timezone.localtime(order.created_at or timezone.now())
    who = [Paragraph('QUOTE FOR', label), Paragraph(name or 'Customer', bold)]
    if phone:
        who.append(Paragraph(phone, sm))
    meta = [Paragraph('ORDER', _style('qm1', parent=label, alignment=TA_RIGHT)),
            Paragraph(order.order_number, number), Spacer(1, 3 * mm),
            Paragraph('DATE', _style('qm2', parent=label, alignment=TA_RIGHT)),
            Paragraph(made.strftime('%d %b %Y'), right)]
    if ready:
        meta += [Spacer(1, 2 * mm), Paragraph('READY', _style('qm3', parent=label, alignment=TA_RIGHT)),
                 Paragraph(ready[:1].upper() + ready[1:], right)]
    top = Table([[who, meta]], colWidths=[width * 0.55, width * 0.45])
    top.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'),
                             ('LINEBEFORE', (0, 0), (0, 0), 2, FARHAT_RED), ('LEFTPADDING', (0, 0), (0, 0), 8)]))
    story += [top, Spacer(1, 8 * mm)]

    rows = [[Paragraph('<b>ITEM</b>', head),
             Paragraph('<b>QTY</b>', _style('qh2', parent=head, alignment=TA_CENTER)),
             Paragraph('<b>UNIT PRICE</b>', _style('qh3', parent=head, alignment=TA_RIGHT)),
             Paragraph('<b>TOTAL</b>', _style('qh4', parent=head, alignment=TA_RIGHT))]]
    num = _style('qq', fontSize=9, textColor=DARK_GREY, alignment=TA_CENTER)
    money = _style('qu', fontSize=9, textColor=DARK_GREY, alignment=TA_RIGHT)
    money_b = _style('qt', fontSize=9, fontName='Helvetica-Bold', textColor=CHARCOAL, alignment=TA_RIGHT)
    for line in order.line_items or []:
        first = [Paragraph(line.get('service_name') or 'Item', cell)]
        spec = _spec(line)
        if spec:
            first.append(Paragraph(spec, sub))
        # Per copy, so quantity x unit price is the line's total (the engine's
        # unit price is per sheet: 2.50 x 3 copies would not read as 30.00).
        quantity = int(line.get('quantity') or 1)
        price = Decimal(str(line.get('base_total') or line.get('total') or 0))
        rows.append([first, Paragraph(str(quantity), num),
                     Paragraph(_fmt(price / quantity), money),
                     Paragraph(_fmt(price), money_b)])
        for extra in line.get('addons') or []:
            label_text = extra.get('service_name') or 'Add-on'
            if extra.get('detail'):
                label_text = f"{label_text} ({extra['detail']})"
            rows.append([Paragraph(label_text, _style('qa', parent=sm, leftIndent=8)),
                         Paragraph(str(extra.get('quantity') or 1), num),
                         Paragraph(_fmt(extra.get('unit_price')), money),
                         Paragraph(_fmt(extra.get('total')), money_b)])
    table = Table(rows, colWidths=[width - 90 * mm, 20 * mm, 35 * mm, 35 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), FARHAT_RED), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 7), ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
        ('LEFTPADDING', (0, 0), (0, -1), 8), ('RIGHTPADDING', (-1, 0), (-1, -1), 8),
        ('LINEBELOW', (0, 1), (-1, -1), 0.5, colors.HexColor('#EFEDEA')),
    ]))
    story += [table, Spacer(1, 6 * mm)]

    total = Table([[Paragraph('<b>Total</b>', _style('qtl', fontSize=11, fontName='Helvetica-Bold',
                                                     textColor=CHARCOAL)),
                    Paragraph(f'<b>{_fmt(order.total)}</b>', _style('qta', fontSize=11, fontName='Helvetica-Bold',
                                                                    textColor=FARHAT_RED, alignment=TA_RIGHT))]],
                  colWidths=[45 * mm, 45 * mm], hAlign='RIGHT')
    total.setStyle(TableStyle([('LINEABOVE', (0, 0), (-1, 0), 0.8, colors.HexColor('#DAD8D4')),
                               ('TOPPADDING', (0, 0), (-1, -1), 6)]))
    story += [total, Spacer(1, 12 * mm)]

    if how == 'counter':
        story.append(Paragraph('You pay at the counter when you collect.', foot_b))
        if code:
            story.append(Paragraph(f'Your pickup code: {code}. Show it at the counter.', foot))
    else:
        story.append(Paragraph('Pay with the link we sent you on WhatsApp, and we start right away.', foot_b))
    story += [Spacer(1, 4 * mm),
              Paragraph('Thank you for choosing Farhat Printing Press&nbsp;&nbsp;FARHAT &#8482;', foot)]

    doc.build(story)
    return buf.getvalue()
