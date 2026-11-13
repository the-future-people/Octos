"""
The WhatsApp receipt as a picture (13 Nov 2026).

A ticket in Farhat red and black on white: the header, "Thank you, <name>",
the receipt and job numbers, the amount paid, how it was paid, the order
(numbered, add-ons under their item, from jobs/services/item_lines.py, the
same lines as the printed receipt and the payment modal), the total and the
balance.

Drawn with Pillow: no browser on the server. render() takes plain data, so it
can be checked without a database; receipt_data() gathers that data from a
Receipt. If anything here fails, the caller sends the text receipt instead.
"""
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

RED = (227, 0, 15)
INK = (11, 11, 12)
GREY = (85, 87, 93)
LIGHT = (107, 109, 115)
RULE = (225, 225, 222)
PAGE = (233, 233, 230)          # around the ticket: shows its notches and edge
WHITE = (255, 255, 255)
PINK = (253, 232, 233)

S = 2                            # drawn at twice the size: sharp on phones
W = 440                          # ticket width in points
MARGIN = 28                      # page around the ticket
PAD = 24                         # inside the ticket

FONT_DIR = Path(__file__).resolve().parent.parent / 'assets' / 'fonts'

TAG_COLOURS = {                  # the modal's tag colours: background, text
    'Colour':    ((252, 231, 243), (157, 23, 77)),
    'B&W':       ((228, 228, 231), (39, 39, 42)),
    'One side':  ((238, 242, 255), (55, 48, 163)),
    'Two sides': ((224, 242, 254), (7, 89, 133)),
    '_':         ((241, 241, 239), (63, 63, 70)),
}

METHOD_STYLE = {                 # chip background, icon square, label
    'CASH':   ((220, 252, 231), (22, 163, 74), 'Cash'),
    'MOMO':   ((255, 244, 214), (255, 204, 0), 'Mobile Money'),
    'POS':    ((219, 234, 254), (37, 99, 235), 'Card (POS)'),
    'SPLIT':  ((241, 241, 239), (63, 63, 70), 'Split payment'),
    'WALLET': ((241, 241, 239), (63, 63, 70), 'Customer wallet'),
}


def _font(weight, size):
    return ImageFont.truetype(str(FONT_DIR / f'DMSans-{weight}.ttf'), size * S)


LOGO = Path(__file__).resolve().parent.parent / 'assets' / 'farhat-logo.png'


def _logo():
    """Farhat's logo for the red header (a white mark on transparent), if present."""
    try:
        return Image.open(LOGO).convert('RGBA') if LOGO.exists() else None
    except Exception:
        return None


def _wrap(draw, text, font, width):
    """Whole words onto as many lines as `width` (in drawn pixels) needs."""
    lines, current = [], ''
    for word in str(text).split():
        trial = f'{current} {word}'.strip()
        if draw.textlength(trial, font=font) <= width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or ['']


class _Ticket:
    """Draws top to bottom; the page is cropped to what was drawn."""

    def __init__(self):
        self.img = Image.new('RGB', ((W + 2 * MARGIN) * S, 4000 * S), PAGE)
        self.d = ImageDraw.Draw(self.img)
        self.x0, self.x1 = MARGIN * S, (MARGIN + W) * S
        self.y = MARGIN * S
        self.top = self.y

    def px(self, v):
        return int(v * S)

    def text(self, xy, s, font, fill, anchor='la'):
        self.d.text(xy, s, font=font, fill=fill, anchor=anchor)

    def rule_with_notches(self):
        mid = self.y + self.px(17)
        self.d.ellipse((self.x0 - self.px(14), mid - self.px(14), self.x0 + self.px(14), mid + self.px(14)), fill=PAGE)
        self.d.ellipse((self.x1 - self.px(14), mid - self.px(14), self.x1 + self.px(14), mid + self.px(14)), fill=PAGE)
        x = self.x0 + self.px(PAD)
        while x < self.x1 - self.px(PAD):
            self.d.line((x, mid, min(x + self.px(7), self.x1 - self.px(PAD)), mid), fill=RULE, width=self.px(2))
            x += self.px(12)
        self.y += self.px(34)


def render(data) -> bytes:
    """The receipt picture as PNG bytes. `data`: see receipt_data()."""
    t = _Ticket()
    d, px = t.d, t.px
    f_label = _font(700, 10)
    f_body = _font(400, 13)
    f_small = _font(400, 12)
    f_bold = _font(700, 14)
    f_value = _font(700, 15)
    inner = W - 2 * PAD

    # White ticket body; drawn tall now, the page is cropped at the end.
    body_top = t.y
    d.rounded_rectangle((t.x0, body_top, t.x1, body_top + px(3800)), radius=px(16), fill=WHITE)

    # Header: the logo on the red band; beside it, at the top, the date and
    # time, the address, the phone and the website (13 Nov 2026).
    header_h = px(96)
    d.rounded_rectangle((t.x0, t.y, t.x1, t.y + header_h + px(16)), radius=px(16), fill=RED)
    d.rectangle((t.x0, t.y + header_h, t.x1, t.y + header_h + px(16)), fill=WHITE)
    # The Farhat bird in white, with the name beside it.
    logo = _logo()
    lx = t.x0 + px(PAD)
    if logo is not None:
        h = px(46)
        w = int(logo.width * h / logo.height)
        mark = logo.resize((w, h), Image.LANCZOS)
        t.img.paste(mark, (lx, t.y + (header_h - h) // 2), mark)
        lx += w + px(8)
    mid = t.y + header_h // 2
    t.text((lx, mid - px(2)), 'FARHAT', _font(700, 17), WHITE, 'ls')
    t.text((lx, mid + px(13)), 'PRINTING PRESS', _font(700, 9), WHITE, 'ls')
    rx, ry = t.x1 - px(PAD), t.y + px(14)
    t.text((rx, ry), f"{data.get('date', '')}  ·  {data.get('time', '')}", _font(700, 13), WHITE, 'ra')
    for k, ln in enumerate((data.get('address', ''), data.get('contact', ''), data.get('website', ''))):
        if ln:
            t.text((rx, ry + px(22) + k * px(16)), ln, _font(500 if k < 2 else 700, 11), WHITE, 'ra')
    t.y += header_h + px(24)

    # The tick and the thank-you.
    cx = (t.x0 + t.x1) // 2
    d.ellipse((cx - px(26), t.y, cx + px(26), t.y + px(52)), fill=PINK)
    d.line((cx - px(11), t.y + px(27), cx - px(3), t.y + px(35), cx + px(12), t.y + px(19)), fill=RED, width=px(4), joint='curve')
    t.y += px(64)
    name = data.get('first_name') or ''
    t.text((cx, t.y), f'Thank you, {name}' if name else 'Thank you', _font(700, 22), INK, 'ma')
    t.y += px(32)
    t.text((cx, t.y), 'Your payment has been received.', f_body, GREY, 'ma')
    t.y += px(26)
    t.rule_with_notches()

    # Receipt, amount paid, date and time, job.
    left, right = t.x0 + px(PAD), t.x1 - px(PAD)

    def pair(lab_l, val_l, lab_r, val_r, red_right=False):
        t.text((left, t.y), lab_l, f_label, LIGHT)
        t.text((right, t.y), lab_r, f_label, LIGHT, 'ra')
        t.text((left, t.y + px(16)), val_l, f_value, INK)
        t.text((right, t.y + px(14)), val_r, _font(700, 19) if red_right else f_value, RED if red_right else INK, 'ra')
        t.y += px(44)

    # The receipt and what was paid; the job itself is described by its items
    # below, as on the printed receipt, not by its number (13 Nov 2026).
    pair('RECEIPT', data.get('receipt_number', ''), 'AMOUNT PAID', f"GHS {data.get('amount_paid', '0.00')}", red_right=True)

    # How it was paid.
    chip_bg, square, method_label = METHOD_STYLE.get(data.get('method', ''), METHOD_STYLE['SPLIT'])
    chip_h = px(58)
    d.rounded_rectangle((left, t.y, right, t.y + chip_h), radius=px(12), fill=chip_bg)
    d.rounded_rectangle((left + px(12), t.y + px(12), left + px(46), t.y + px(46)), radius=px(9), fill=square)
    t.text((left + px(29), t.y + px(29)), method_label[:1], _font(700, 15), INK if data.get('method') == 'MOMO' else WHITE, 'mm')
    t.text((left + px(58), t.y + px(11)), data.get('method_label') or method_label, f_bold, INK)
    t.text((left + px(58), t.y + px(31)), data.get('method_note', '')[:52], f_small, GREY)
    t.y += chip_h + px(18)

    # The order.
    items = data.get('items') or []
    count = sum(1 for i in items if not i.get('is_addon'))
    t.text((left, t.y), f"YOUR ORDER · {count} ITEM{'' if count == 1 else 'S'}", f_label, LIGHT)
    t.y += px(20)
    amount_room = px(80)
    for it in items:
        addon = it.get('is_addon')
        indent = px(30) if addon else 0
        lead_x = left + indent
        if addon:
            t.text((lead_x, t.y + px(1)), '+', _font(700, 15), RED)
        else:
            d.ellipse((lead_x, t.y, lead_x + px(20), t.y + px(20)), fill=INK)
            t.text((lead_x + px(10), t.y + px(10)), str(it.get('number') or ''), _font(700, 11), WHITE, 'mm')
        text_x = lead_x + px(30)
        t.text((right, t.y + px(1)), f"GHS {it.get('amount', '0.00')}", f_bold, INK, 'ra')
        for k, ln in enumerate(_wrap(d, it.get('name', ''), f_bold, right - amount_room - text_x)):
            t.text((text_x, t.y + px(1) + k * px(19)), ln, f_bold, INK)
            last = k
        t.y += px(20) + last * px(19)
        detail = it.get('sum') or (it.get('count') if it.get('count') not in (None, '', '1') else '')
        if detail:
            for ln in _wrap(d, detail, f_small, right - text_x):
                t.text((text_x, t.y + px(2)), ln, f_small, GREY)
                t.y += px(17)
        # The choices as coloured tags, side by side, as in the payment modal.
        tags = it.get('tags') or []
        if tags:
            f_tag = _font(700, 10)
            tx, ty = text_x, t.y + px(5)
            for tag in tags:
                bg, fg = TAG_COLOURS.get(tag, TAG_COLOURS['_'])
                w = int(d.textlength(tag, font=f_tag)) + px(12)
                if tx + w > right and tx > text_x:
                    tx, ty = text_x, ty + px(22)
                d.rounded_rectangle((tx, ty, tx + w, ty + px(18)), radius=px(5), fill=bg)
                t.text((tx + w // 2, ty + px(9)), tag, f_tag, fg, 'mm')
                tx += w + px(5)
            t.y = ty + px(18)
        t.y += px(12)

    d.line((left, t.y, right, t.y), fill=RULE, width=px(1))
    t.y += px(12)
    t.text((left, t.y), 'Total', _font(700, 15), INK)
    t.text((right, t.y), f"GHS {data.get('total', '0.00')}", _font(700, 15), INK, 'ra')
    t.y += px(24)
    t.text((left, t.y), 'Balance', f_body, GREY)
    t.text((right, t.y), f"GHS {data.get('balance', '0.00')}", f_body, GREY, 'ra')
    t.y += px(26)
    t.rule_with_notches()

    # Footer.
    t.text((cx, t.y), 'Keep this receipt for reprints and collection.', f_small, GREY, 'ma')
    t.y += px(20)
    t.text((cx, t.y), data.get('website') or 'farhatprintingpress.com', _font(700, 12), RED, 'ma')
    t.y += px(48)                    # room above the scalloped edge

    # Scalloped bottom edge: page-coloured circles bite into the ticket.
    bottom = t.y
    d.rectangle((t.x0, bottom, t.x1, bottom + px(3800)), fill=PAGE)
    n, r = 7, px(17)
    step = (t.x1 - t.x0) / n
    for i in range(n):
        x = t.x0 + step * i + step / 2
        d.ellipse((x - r, bottom - r, x + r, bottom + r), fill=PAGE)

    out = t.img.crop((0, 0, t.img.width, bottom + px(MARGIN)))
    buf = BytesIO()
    out.save(buf, format='PNG', optimize=True)
    return buf.getvalue()


# Farhat's official details. Calls and WhatsApp share one number for every
# branch; the address comes from the branch when it has one.
OFFICIAL_PHONE = '055 196 9777'
WEBSITE = 'farhatprintingpress.com'
WESTLAND = ('63 Westlands Ave, Accra', 'GE-328-6296')


def receipt_data(receipt) -> dict:
    """The facts render() draws, gathered from a Receipt."""
    from django.utils import timezone

    from apps.jobs.services.item_lines import describe_job

    job = receipt.job
    when = timezone.localtime(receipt.created_at)
    branch = getattr(job, 'branch', None) or getattr(receipt, 'branch', None)
    address = (getattr(branch, 'address', '') or '').strip() or WESTLAND[0]
    gps = (getattr(branch, 'gps_address', '') or getattr(branch, 'ghana_post_gps', '') or '').strip() or WESTLAND[1]

    words = (receipt.customer_name or '').split(' (')[0].split()
    titles = {'MR', 'MRS', 'MS', 'DR', 'MISS', 'PROF', 'REV'}
    while words and words[0].rstrip('.').upper() in titles:
        words = words[1:]
    first = words[0] if words and words[0].lower() not in ('walk-in', 'walk') else ''

    method = receipt.payment_method
    ref = getattr(receipt, 'momo_reference', '') or getattr(receipt, 'pos_approval_code', '') or ''
    cashier = getattr(getattr(receipt, 'cashier', None), 'full_name', '') or ''
    note = ' · '.join(p for p in (f'Ref {ref}' if ref else '', f'received by {cashier}' if cashier else '') if p)

    return {
        'date': when.strftime('%d %b %Y').upper(),
        'time': when.strftime('%I:%M %p').lstrip('0'),
        'address': address,
        'contact': f'GPS {gps} · {OFFICIAL_PHONE}',
        'website': WEBSITE,
        'first_name': first,
        'receipt_number': receipt.receipt_number,
        'amount_paid': f"{receipt.amount_paid:.2f}",
        'method': method,
        'method_label': 'Card (POS)' if method == 'POS' else receipt.get_payment_method_display(),
        'method_note': note,
        'items': describe_job(job.line_items.select_related('service').order_by('position')) if job else [],
        'total': f"{(job.estimated_cost if job else receipt.amount_paid):.2f}",
        'balance': f"{(receipt.balance_due or 0):.2f}",
    }
