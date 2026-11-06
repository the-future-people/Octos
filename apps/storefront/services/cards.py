"""
Cards: a message drawn as an image, for WhatsApp, where text alone can't
show a layout (Khofi's design, 6 Nov 2026; the wording agreed for WhatsApp).

WhatsApp text can only be bold, italic and line breaks: no boxes, colours
or icons. So the payment confirmation is drawn here, in the Octos font,
and sent as an image with a short caption carrying the live link (a link
inside a picture can't be tapped). SMS keeps its one-credit text.
"""
import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ASSETS = Path(__file__).resolve().parent.parent / 'assets' / 'cards'

S = 2                      # drawn at twice the size, crisp on any phone
W, PAD, MARGIN = 760 * S, 40 * S, 28 * S
BG, CARD = (243, 238, 230), (255, 255, 255)
INK, INK2 = (22, 24, 29), (95, 101, 112)
GREEN, GREEN_BG = (34, 164, 71), (217, 245, 223)
RED = (229, 83, 61)
MINT, MINT_LINE, TEAL = (227, 243, 236), (200, 226, 214), (15, 110, 92)
PILL = (240, 240, 239)

_fonts = {}


def _font(size, weight):
    key = (size, weight)
    if key not in _fonts:
        f = ImageFont.truetype(str(ASSETS / 'DMSans.ttf'), size * S)
        f.set_variation_by_axes([14, weight])
        _fonts[key] = f
    return _fonts[key]


def paid_card(order):
    """The payment confirmation for an order, as PNG bytes."""
    from apps.storefront.services.messages import (
        STOREFRONT, _branch_name, _first_name, _money, _ready, _ref, _what,
    )
    name, when, where = _first_name(order), _ready(order), _branch_name(order)
    ready = [("We're on it:", False), (_what(order), True)]
    if when:
        ready += [('should be ready by about', False), (when, True)]
    if where:
        ready += [('at', False), (f'{where}.', True)]
    else:
        ready[-1] = (ready[-1][0] + '.', ready[-1][1])
    link = f'{STOREFRONT}/t/{order.short_code}'.replace('https://', '').replace('http://', '')
    return render(
        title=f'Thanks, {name}!' if name else 'Thank you!',
        paid=[('We got your payment', False), (f'(GHS {_money(order.total)}).', True)],
        ready=ready,
        note="We'll let you know as soon as it's ready!",
        link=link,
        ref=str(_ref(order)),
    )


def render(title, paid, ready, note, link, ref):
    regular, bold = _font(21, 400), _font(21, 700)
    probe = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    text_x, lh = PAD + 64 * S, 32 * S
    text_w = W - text_x - PAD

    paid_lines = _wrap(paid, text_w, probe, regular, bold)
    ready_lines = _wrap(ready, text_w, probe, regular, bold)
    note_lines = _wrap([(note, False)], W - 2 * PAD, probe, regular, bold)
    box_h, pill_h = 104 * S, 56 * S
    h = (PAD + 84 * S + len(paid_lines) * lh + 28 * S + len(ready_lines) * lh + 28 * S
         + len(note_lines) * lh + 28 * S + box_h + 24 * S + pill_h + PAD)

    img = Image.new('RGB', (W + 2 * MARGIN, h + 2 * MARGIN), BG)
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((MARGIN, MARGIN, MARGIN + W, MARGIN + h), radius=36 * S, fill=CARD)
    x0, y = MARGIN, MARGIN + PAD

    title_font = _font(30, 500)
    draw.text((x0 + PAD, y), title, font=title_font, fill=INK)
    hands = Image.open(ASSETS / 'pray.png').convert('RGBA').resize((40 * S, 40 * S), Image.LANCZOS)
    img.paste(hands, (int(x0 + PAD + probe.textlength(title, font=title_font) + 14 * S), y + 2 * S), hands)
    y += 84 * S

    _check(draw, x0 + PAD, y - 6 * S)
    y = _lines(draw, paid_lines, x0 + text_x, y, lh) + 28 * S
    _photo(draw, x0 + PAD + 2 * S, y)
    y = _lines(draw, ready_lines, x0 + text_x, y, lh) + 28 * S
    y = _lines(draw, note_lines, x0 + PAD, y, lh) + 28 * S

    draw.rounded_rectangle((x0 + PAD, y, x0 + W - PAD, y + box_h), radius=22 * S, fill=MINT)
    _link(img, x0 + PAD + 18 * S, y + 30 * S)
    draw.line([(x0 + PAD + 80 * S, y + 22 * S), (x0 + PAD + 80 * S, y + box_h - 22 * S)], fill=MINT_LINE, width=2 * S)
    draw.text((x0 + PAD + 100 * S, y + 22 * S), 'Follow it live here:', font=_font(18, 400), fill=INK2)
    draw.text((x0 + PAD + 100 * S, y + 52 * S), link, font=bold, fill=TEAL)
    y += box_h + 24 * S

    label = 'Reference: '
    pill_w = 84 * S + probe.textlength(label, font=regular) + probe.textlength(ref, font=bold)
    draw.rounded_rectangle((x0 + PAD, y, x0 + PAD + pill_w, y + pill_h), radius=18 * S, fill=PILL)
    _ticket(draw, x0 + PAD + 18 * S, y + 19 * S)
    tx = x0 + PAD + 60 * S
    draw.text((tx, y + 14 * S), label, font=regular, fill=INK2)
    draw.text((tx + probe.textlength(label, font=regular), y + 14 * S), ref, font=bold, fill=INK)

    out = io.BytesIO()
    img.save(out, format='PNG', optimize=True)
    return out.getvalue()


def _wrap(segments, width, draw, regular, bold):
    """[(text, bold)] into lines of [(text, font)], wrapped at words."""
    lines, line, x = [], [], 0
    for text, is_bold in segments:
        f = bold if is_bold else regular
        for word in (text or '').split(' '):
            if not word:
                continue
            piece = (' ' if line else '') + word
            w = draw.textlength(piece, font=f)
            if line and x + w > width:
                lines.append(line)
                line, x, piece = [], 0, word
                w = draw.textlength(piece, font=f)
            line.append((piece, f))
            x += w
    if line:
        lines.append(line)
    return lines


def _lines(draw, lines, x, y, lh):
    for line in lines:
        cx = x
        for text, f in line:
            draw.text((cx, y), text, font=f, fill=INK)
            cx += draw.textlength(text, font=f)
        y += lh
    return y


def _check(draw, x, y):
    draw.ellipse((x, y, x + 44 * S, y + 44 * S), fill=GREEN_BG)
    draw.line([(x + 13 * S, y + 23 * S), (x + 20 * S, y + 30 * S), (x + 32 * S, y + 15 * S)],
              fill=GREEN, width=4 * S, joint='curve')


def _photo(draw, x, y):
    s = 40 * S
    draw.rounded_rectangle((x, y, x + s, y + s * 0.85), radius=6 * S, outline=RED, width=3 * S)
    draw.ellipse((x + 9 * S, y + 8 * S, x + 16 * S, y + 15 * S), fill=RED)
    draw.polygon([(x + 6 * S, y + 28 * S), (x + 17 * S, y + 18 * S), (x + 24 * S, y + 24 * S),
                  (x + 29 * S, y + 19 * S), (x + 35 * S, y + 28 * S)], fill=RED)


def _link(img, x, y):
    """Two interlocking links, drawn flat and turned 45 degrees."""
    size = 44 * S
    layer = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    w, h, cy = 20 * S, 12 * S, size // 2
    d.rounded_rectangle((4 * S, cy - h // 2, 4 * S + w, cy + h // 2), radius=6 * S, outline=TEAL, width=3 * S)
    d.rounded_rectangle((size - 4 * S - w, cy - h // 2, size - 4 * S, cy + h // 2), radius=6 * S, outline=TEAL, width=3 * S)
    d.line([(16 * S, cy), (size - 16 * S, cy)], fill=TEAL, width=3 * S)
    layer = layer.rotate(45, resample=Image.BICUBIC)
    img.paste(layer, (int(x), int(y)), layer)


def _ticket(draw, x, y):
    draw.rounded_rectangle((x, y, x + 28 * S, y + 18 * S), radius=4 * S, outline=INK, width=3 * S)
    draw.ellipse((x - 4 * S, y + 5 * S, x + 4 * S, y + 13 * S), fill=PILL)
    draw.ellipse((x + 24 * S, y + 5 * S, x + 32 * S, y + 13 * S), fill=PILL)
    draw.ellipse((x + 11 * S, y + 6 * S, x + 17 * S, y + 12 * S), fill=INK)


# Which notifications go as a card on WhatsApp. Any other kind is text.
CARDS = {
    'paid': paid_card,
}
