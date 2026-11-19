"""
Paper sizes, the way a customer understands them (19 Nov 2026).

A customer testing Octos found it too technical about paper sizes, and asked
to *see* what B6 or A4 looks like. And Octos told her sizes below A4 were
something we don't print, when every one of them is printed on an A4 sheet
and cut out (Khofi: "we just need to fit it to the A4 then print and cut").

So for any size Octos can say, in plain words:
  what it is like        "a quarter of an A4 sheet, about postcard size"
  how big                in centimetres, only when asked
  how we print it        on A4 and cut to size, or A4 / A3 as it is
  how many fit on A4     so the price is per A4 sheet, like any printing
and draw them to scale against an A4 sheet, as a picture for the chat.

facts() and render() take no database: they can be checked on their own.
"""
import math
import re
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

A4 = (210, 297)
A3 = (297, 420)

# key: (name the customer sees, width mm, height mm, what it is like)
SIZES = {
    'A2': ('A2', 420, 594, 'four A4 sheets put together, poster size'),
    'A3': ('A3', 297, 420, 'two A4 sheets side by side'),
    'B4': ('B4', 250, 353, 'a bit bigger than A4'),
    'A4': ('A4', 210, 297, 'a normal printing sheet'),
    'LETTER': ('Letter', 216, 279, 'the American normal sheet, almost the same as A4'),
    'B5': ('B5', 176, 250, 'a bit smaller than A4, like an exercise book'),
    'A5': ('A5', 148, 210, 'half of an A4 sheet'),
    'B6': ('B6', 125, 176, 'between A5 and A6, about the size of a storybook page'),
    '5X7': ('5 x 7 in', 127, 178, 'a photo frame size'),
    'DL': ('DL', 99, 210, 'a third of an A4 sheet, long and narrow'),
    'A6': ('A6', 105, 148, 'a quarter of an A4 sheet, about postcard size'),
    '4X6': ('4 x 6 in', 102, 152, 'a normal photo print, postcard size'),
    'A7': ('A7', 74, 105, 'an eighth of an A4 sheet, pocket size'),
    'CARD': ('Business card', 85, 55, 'a business card'),
}

ALIASES = {
    'LETTERSIZE': 'LETTER', 'USLETTER': 'LETTER',
    'HALFA4': 'A5', 'HALFOFA4': 'A5', 'QUARTERA4': 'A6', 'QUARTEROFA4': 'A6',
    'POSTCARD': 'A6', 'POSTCARDSIZE': 'A6',
    '6X4': '4X6', '4R': '4X6', '7X5': '5X7', '5R': '5X7',
    'BUSINESSCARD': 'CARD', 'COMPLIMENTARYCARD': 'CARD', 'COMPLIMENTCARD': 'CARD',
    'EXERCISEBOOK': 'B5', 'POSTER': 'A2',
}


def key_for(name):
    """'b6', 'A 5', '4 by 6', 'half A4', 'postcard' → the SIZES key, or None."""
    raw = (name or '').upper().replace('BY', 'X').replace('×', 'X').replace('*', 'X')
    raw = re.sub(r'\b(SIZE|PAPER|SHEET|INCHES|INCH|IN)\b', '', raw)
    flat = re.sub(r'[^A-Z0-9X]', '', raw)
    if flat in SIZES:
        return flat
    return ALIASES.get(flat)


def fits_on_a4(w, h):
    """How many pieces of w x h mm one A4 sheet holds, either way round."""
    upright = (A4[0] // w) * (A4[1] // h)
    turned = (A4[0] // h) * (A4[1] // w)
    return int(max(upright, turned))


def facts(names, copies=None):
    """What Octos may say about each size: plain words, centimetres, how it's printed."""
    out, unknown = [], []
    for name in names or []:
        key = key_for(name)
        if key is None:
            unknown.append(str(name))
            continue
        label, w, h, like = SIZES[key]
        row = {'size': label, 'like': like,
               'centimetres': f'{_cm(w)} x {_cm(h)} cm'}
        if w * h > A3[0] * A3[1]:
            row['how_we_print'] = 'bigger than A3: a large format job. Hand it to a person for the price.'
        elif (w, h) == A3:
            row['how_we_print'] = 'printed on an A3 sheet as it is'
        elif w * h > A4[0] * A4[1] or w > A4[0] and h > A4[0]:
            row['how_we_print'] = 'printed on an A3 sheet and cut to size; price it as A3 printing per sheet'
        elif key in ('A4', 'LETTER'):
            row['how_we_print'] = 'printed on an A4 sheet as it is'
        else:
            n = fits_on_a4(w, h)
            row['how_we_print'] = 'printed on an A4 sheet and cut to size; price it as A4 printing per sheet'
            row['fit_on_one_a4'] = n
            if copies:
                row['copies'] = int(copies)
                row['a4_sheets_needed'] = math.ceil(int(copies) / n)
        out.append(row)
    result = {'sizes': out}
    if unknown:
        result['not_known'] = unknown
        result['say'] = ('For a size not listed, ask the customer for the width and height, '
                         'or hand it to a person.')
    return result


def _cm(mm):
    cm = mm / 10
    return f'{cm:.1f}'.rstrip('0').rstrip('.')


# ── The picture ────────────────────────────────────────────────────────────

INK = (11, 11, 12)
GREY = (96, 98, 104)
PAGE = (236, 236, 233)
WHITE = (255, 255, 255)
RED = (227, 0, 15)
SHEET_LINE = (150, 152, 158)
TINTS = [(227, 0, 15), (37, 99, 235), (22, 163, 74), (232, 150, 0)]

S = 2
W = 420
PAD = 22
FONT_DIR = Path(__file__).resolve().parents[2] / 'finance' / 'assets' / 'fonts'


WEIGHTS = {'Regular': 400, 'Medium': 500, 'Bold': 700}


def _font(weight, size):
    return ImageFont.truetype(str(FONT_DIR / f'DMSans-{WEIGHTS[weight]}.ttf'), int(size * S))


def render(names):
    """
    The sizes drawn to scale on one card, every one against an A4 sheet,
    each corner-to-corner from the top left so the difference is plain.
    Up to four sizes. Returns PNG bytes, or None if none is known.
    """
    keys = []
    for name in names or []:
        key = key_for(name)
        if key and key not in keys and key != 'A4':
            keys.append(key)
    keys = keys[:4]
    if not keys and not any(key_for(n) == 'A4' for n in names or []):
        return None

    shapes = [('A4',) + SIZES['A4'][1:3]] + [(k,) + SIZES[k][1:3] for k in keys]
    biggest_w = max(w for _, w, _h in shapes)
    biggest_h = max(h for _, _w, h in shapes)

    area_w = W - 2 * PAD
    scale = min(area_w / biggest_w, 330 / biggest_h)
    area_h = biggest_h * scale

    legend_rows = len(shapes)
    height = 64 + area_h + 26 + legend_rows * 44 + 40
    img = Image.new('RGB', (int(W * S), int(height * S)), WHITE)
    d = ImageDraw.Draw(img)
    p = lambda v: int(v * S)  # noqa: E731

    d.rectangle([0, 0, p(W), p(48)], fill=INK)
    d.rectangle([0, p(48), p(W), p(51)], fill=RED)
    d.text((p(PAD), p(14)), 'Paper sizes', font=_font('Bold', 17), fill=WHITE)
    d.text((p(W - PAD), p(17)), 'Farhat Printing Press', font=_font('Medium', 10), fill=(200, 200, 200),
           anchor='ra')

    top = 64
    left = (W - biggest_w * scale) / 2
    d.rectangle([p(left - 6), p(top - 6), p(left + biggest_w * scale + 6), p(top + area_h + 6)], fill=PAGE)

    # Biggest first, so smaller ones sit on top and every edge shows.
    order = sorted(shapes, key=lambda s: -(s[1] * s[2]))
    for key, w, h in order:
        x1, y1 = left + w * scale, top + h * scale
        if key == 'A4':
            d.rectangle([p(left), p(top), p(x1), p(y1)], fill=WHITE, outline=SHEET_LINE, width=p(1.5))
        else:
            tint = TINTS[keys.index(key) % len(TINTS)]
            soft = tuple(int(c + (255 - c) * 0.82) for c in tint)
            d.rectangle([p(left), p(top), p(x1), p(y1)], fill=soft, outline=tint, width=p(2))
        name = SIZES[key][0]
        d.text((p(x1 - 6), p(y1 - 6)), name, font=_font('Bold', 12),
               fill=GREY if key == 'A4' else TINTS[keys.index(key) % len(TINTS)], anchor='rd')

    y = top + area_h + 26
    for key, w, h in shapes:
        label, _, _, like = SIZES[key]
        colour = SHEET_LINE if key == 'A4' else TINTS[keys.index(key) % len(TINTS)]
        d.rounded_rectangle([p(PAD), p(y + 3), p(PAD + 12), p(y + 15)], radius=p(3), fill=colour)
        d.text((p(PAD + 20), p(y)), f'{label}  ·  {_cm(w)} x {_cm(h)} cm', font=_font('Bold', 12), fill=INK)
        words = like[:1].upper() + like[1:]
        if w * h < A4[0] * A4[1] and key != 'LETTER':
            n = fits_on_a4(w, h)
            words += f' · {n} fit on one A4' if n > 1 else ' · printed on A4 and cut'
        d.text((p(PAD + 20), p(y + 18)), words, font=_font('Regular', 11), fill=GREY)
        y += 44

    smaller = any(w * h < A4[0] * A4[1] for k, w, h in shapes if k not in ('A4', 'LETTER'))
    d.text((p(PAD), p(y + 6)),
           'Drawn to scale. Smaller sizes are printed on A4 and cut out.' if smaller else 'Drawn to scale.',
           font=_font('Regular', 10), fill=GREY)
    buf = BytesIO()
    img.save(buf, 'PNG', optimize=True)
    return buf.getvalue()
