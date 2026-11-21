"""
The customer's statement, as a PDF (21 Nov 2026).

One page that says what they owe us: the jobs owed from before (work
delivered and not paid, or a balance after a deposit), the new work waiting
for payment, and the total. Built from owing.statement(), so it always
agrees with the cashier's Balances, the customer file and Octos.

Each job is listed by its number, so a customer paying part can say which
job they're paying: payments go where they point, nothing is cleared
automatically. House style follows the proforma.
"""
import base64
import io

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.core.branding import LOGO_B64
from apps.core.pdf import base

RED, INK, BODY, MUTED, BG = base.FARHAT_RED, base.INK, base.BODY, base.MUTED, base.BG
WHITE = colors.white


def _s(name, **kw):
    return ParagraphStyle(name, **kw)


def _ghs(n):
    return f"GHS {float(n or 0):,.2f}"


def _what(job):
    try:
        from apps.jobs.services.reminders import items_phrase
        phrase = items_phrase(job)
        return phrase if phrase and phrase != 'order' else (job.title or 'Job')
    except Exception:
        return job.title or 'Job'


def build_statement_pdf(st, branch=None) -> bytes:
    customer = st['customer']
    buf = io.BytesIO()
    page_w, _ = A4
    margin = 20 * mm
    width = page_w - 2 * margin
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=margin, rightMargin=margin, topMargin=0,
                            bottomMargin=18 * mm, title=f'Statement for {customer.display_name}')
    sm = _s('sm', fontSize=9, fontName='Helvetica', textColor=BODY)
    bold = _s('b', fontSize=10, fontName='Helvetica-Bold', textColor=INK)
    lbl = _s('l', fontSize=7, fontName='Helvetica-Bold', textColor=colors.HexColor('#999999'), leading=10)
    head = _s('h', fontSize=8, fontName='Helvetica-Bold', textColor=WHITE)
    head_r = _s('hr', parent=head, alignment=TA_RIGHT)
    cell = _s('c', fontSize=9, fontName='Helvetica-Bold', textColor=INK)
    sub = _s('cs', fontSize=8, fontName='Helvetica', textColor=MUTED)
    num = _s('n', fontSize=9, fontName='Helvetica', textColor=BODY, alignment=TA_RIGHT)
    num_b = _s('nb', parent=num, fontName='Helvetica-Bold', textColor=INK)
    foot = _s('f', fontSize=8, fontName='Helvetica', textColor=MUTED, alignment=TA_CENTER, leading=12)
    foot_b = _s('fb', parent=foot, fontName='Helvetica-Bold', textColor=BODY)

    story = []
    logo = Image(io.BytesIO(base64.b64decode(LOGO_B64)), width=14 * mm, height=14 * mm)
    band = Table([[logo,
                   [Paragraph('<b>Farhat Printing Press</b>', _s('co', fontSize=16, fontName='Helvetica-Bold',
                                                                 textColor=WHITE, leading=20)),
                    Paragraph('Professional Printing Services', _s('cs2', fontSize=8,
                                                                   textColor=colors.HexColor('#FFAAAA')))],
                   Paragraph('<b>STATEMENT</b>', _s('ty', fontSize=11, fontName='Helvetica-Bold', textColor=WHITE,
                                                    alignment=TA_RIGHT))]],
                 colWidths=[18 * mm, width - 78 * mm, 60 * mm])
    band.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), RED), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                              ('TOPPADDING', (0, 0), (-1, -1), 10), ('BOTTOMPADDING', (0, 0), (-1, -1), 10)]))
    story.append(band)
    if branch is not None:
        contact = ' | '.join(filter(None, [branch.name, branch.phone or '', branch.email or '']))
        strip = Table([[Paragraph(contact, _s('ct', fontSize=8, textColor=BODY, alignment=TA_CENTER))]],
                      colWidths=[width])
        strip.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), BG), ('TOPPADDING', (0, 0), (-1, -1), 5),
                                   ('BOTTOMPADDING', (0, 0), (-1, -1), 5)]))
        story.append(strip)
    story.append(Spacer(1, 8 * mm))

    who = [Paragraph('STATEMENT FOR', lbl), Paragraph(customer.display_name, bold)]
    if customer.phone:
        who.append(Paragraph(customer.phone, sm))
    meta = [Paragraph('DATE', _s('l2', parent=lbl, alignment=TA_RIGHT)),
            Paragraph(timezone.localdate().strftime('%d %b %Y'), num_b),
            Spacer(1, 3 * mm),
            Paragraph('TOTAL DUE', _s('l3', parent=lbl, alignment=TA_RIGHT)),
            Paragraph(f"<b>{_ghs(st['total'])}</b>", _s('td', fontSize=13, fontName='Helvetica-Bold',
                                                         textColor=RED, alignment=TA_RIGHT))]
    top = Table([[who, meta]], colWidths=[width * 0.55, width * 0.45])
    top.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LINEBEFORE', (0, 0), (0, 0), 2, RED),
                             ('LEFTPADDING', (0, 0), (0, 0), 8)]))
    story.append(top)

    def section(title, jobs, total):
        story.append(Spacer(1, 7 * mm))
        story.append(Paragraph(f'<b>{title}</b>', bold))
        story.append(Spacer(1, 2 * mm))
        rows = [[Paragraph('JOB', head), Paragraph('DATE', head), Paragraph('AMOUNT', head_r),
                 Paragraph('PAID', head_r), Paragraph('BALANCE', head_r)]]
        for j in jobs:
            rows.append([[Paragraph(j.job_number, cell), Paragraph(_what(j), sub)],
                         Paragraph(timezone.localtime(j.handed_over_at or j.created_at).strftime('%d %b %Y'), sm),
                         Paragraph(_ghs(j.estimated_cost), num), Paragraph(_ghs(j.amount_paid), num),
                         Paragraph(_ghs(j.balance_due), num_b)])
        rows.append(['', '', '', Paragraph('<b>Subtotal</b>', num_b), Paragraph(f'<b>{_ghs(total)}</b>', num_b)])
        t = Table(rows, colWidths=[width - 115 * mm, 25 * mm, 30 * mm, 30 * mm, 30 * mm], repeatRows=1)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), RED), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LINEBELOW', (0, 1), (-1, -2), 0.5, colors.HexColor('#EFEDEA')),
            ('LINEABOVE', (0, -1), (-1, -1), 0.8, colors.HexColor('#DAD8D4')),
        ]))
        story.append(t)

    if st['owed']:
        section('Owed from before', st['owed'], st['owed_total'])
    if st['current']:
        section('New work', st['current'], st['current_total'])
    if not st['owed'] and not st['current']:
        story.append(Spacer(1, 8 * mm))
        story.append(Paragraph('Nothing is owed. Thank you!', bold))

    story.append(Spacer(1, 6 * mm))
    total = Table([[Paragraph('<b>Total due</b>', _s('tl', fontSize=11, fontName='Helvetica-Bold', textColor=INK)),
                    Paragraph(f"<b>{_ghs(st['total'])}</b>", _s('ta', fontSize=11, fontName='Helvetica-Bold',
                                                                 textColor=RED, alignment=TA_RIGHT))]],
                  colWidths=[45 * mm, 45 * mm], hAlign='RIGHT')
    total.setStyle(TableStyle([('LINEABOVE', (0, 0), (-1, 0), 0.8, colors.HexColor('#DAD8D4')),
                               ('TOPPADDING', (0, 0), (-1, -1), 6)]))
    story.append(total)

    story.append(Spacer(1, 12 * mm))
    story.append(Paragraph('Paying part? Tell us the job number you are paying for.', foot_b))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph('Kindly make payment to', foot))
    story.append(Paragraph('Mobile Money: 0556244194', foot_b))
    story.append(Paragraph('Account Name: Adjei Kingsford', foot_b))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph('Thank you for choosing Farhat Printing Press&nbsp;&nbsp;FARHAT &#8482;', foot))
    doc.build(story)
    return buf.getvalue()


def send_statement(customer, branch=None, branch_ids=None):
    """
    The statement on WhatsApp, in the customer's chat. Returns (sent, reason).
    WhatsApp only lets us write to someone who wrote in the last 24 hours.
    """
    from apps.communications.services.whatsapp_outbound import WindowClosed, send_text, thread_for
    from apps.finance.services.owing import statement
    st = statement(customer, branch_ids)
    if st['total'] <= 0:
        return False, f'{customer.display_name} owes nothing.'
    chat = thread_for(customer.phone) if customer.phone else None
    if chat is None:
        return False, f'{customer.display_name} has no WhatsApp chat with us. Print it or download it instead.'
    from apps.communications.services.names import name_for
    name = name_for(chat, customer)
    caption = (f"Here's your statement{', ' + name if name else ''}: {_ghs(st['total'])} in all. "
               'Each job is listed by number, so tell us which one you are paying for. Thank you 🙏')
    pdf = build_statement_pdf(st, branch)
    try:
        send_text(chat, caption, kind='statement', document=pdf,
                  filename=f"Statement-{timezone.localdate():%Y-%m-%d}.pdf")
    except (WindowClosed, ValueError):
        return False, ("WhatsApp only lets us write to someone who messaged us in the last 24 hours. "
                       'Download it and share it, or send it once they write.')
    return True, ''
