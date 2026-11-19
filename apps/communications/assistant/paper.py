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


# ── The pictures ───────────────────────────────────────────────────────────
#
# Two pictures, both drawn to scale (19 Nov 2026, from a tester's "How would
# it look like??"):
#   render()   which size is which: the sizes asked about against an A4
#              sheet, a phone beside them so the size means something
#   preview()  the customer's own photo, laid out on the sheet as we print
#              it, cut lines in, and the piece they take home beside it

INK = (11, 11, 12)
GREY = (96, 98, 104)
SOFT = (150, 152, 158)
PAGE = (240, 240, 237)
WHITE = (255, 255, 255)
RED = (227, 0, 15)
TINTS = [(227, 0, 15), (37, 99, 235), (22, 163, 74), (232, 150, 0)]
PHONE = (71, 147)      # an everyday phone, in mm: what "a bit bigger than your phone" means

S = 2                  # drawn at twice the size, for sharp text on a phone
PAD = 22
FONT_DIR = Path(__file__).resolve().parents[2] / 'finance' / 'assets' / 'fonts'
WEIGHTS = {'Regular': 400, 'Medium': 500, 'Bold': 700}


def _font(weight, size):
    return ImageFont.truetype(str(FONT_DIR / f'DMSans-{WEIGHTS[weight]}.ttf'), int(size * S))


def _p(v):
    return int(round(v * S))


def _card(width, height, title):
    img = Image.new('RGB', (_p(width), _p(height)), WHITE)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, _p(width), _p(48)], fill=INK)
    d.rectangle([0, _p(48), _p(width), _p(51)], fill=RED)
    d.text((_p(PAD), _p(14)), title, font=_font('Bold', 17), fill=WHITE)
    d.text((_p(width - PAD), _p(18)), 'Farhat Printing Press', font=_font('Medium', 10),
           fill=(200, 200, 200), anchor='ra')
    return img, d


def _png(img):
    buf = BytesIO()
    img.save(buf, 'PNG', optimize=True)
    return buf.getvalue()


def _phone(d, x, y, scale):
    """A plain phone outline, w x h mm at this scale, its top left at x, y."""
    w, h = PHONE[0] * scale, PHONE[1] * scale
    d.rounded_rectangle([_p(x), _p(y), _p(x + w), _p(y + h)], radius=_p(min(w, h) * 0.14),
                        fill=(34, 34, 38), outline=INK, width=_p(1))
    inset = max(w * 0.06, 2)
    d.rounded_rectangle([_p(x + inset), _p(y + inset * 2.2), _p(x + w - inset), _p(y + h - inset * 2.2)],
                        radius=_p(min(w, h) * 0.06), fill=(70, 72, 80))
    d.text((_p(x + w / 2), _p(y + h + 6)), 'A phone', font=_font('Medium', 10), fill=GREY, anchor='ma')
    return w, h


def _dashed(d, a, b, colour=RED, dash=5, gap=4, width=1.4):
    """A dotted cut line from a to b (horizontal or vertical)."""
    (x1, y1), (x2, y2) = a, b
    length = abs(x2 - x1) + abs(y2 - y1)
    pos = 0
    while pos < length:
        end = min(pos + dash, length)
        if x1 == x2:
            d.line([_p(x1), _p(y1 + pos), _p(x1), _p(y1 + end)], fill=colour, width=_p(width))
        else:
            d.line([_p(x1 + pos), _p(y1), _p(x1 + end), _p(y1)], fill=colour, width=_p(width))
        pos += dash + gap


def render(names):
    """
    The sizes asked about, drawn to scale against an A4 sheet, corner to
    corner from the top left, each labelled inside; a phone beside them.
    Up to three sizes. Returns PNG bytes, or None if none is known.
    """
    keys = []
    for name in names or []:
        key = key_for(name)
        if key and key not in keys and key != 'A4':
            keys.append(key)
    keys = keys[:3]
    if not keys and not any(key_for(n) == 'A4' for n in names or []):
        return None

    shapes = [('A4',) + SIZES['A4'][1:3]] + [(k,) + SIZES[k][1:3] for k in keys]
    big_w = max(w for _, w, _h in shapes)
    big_h = max(h for _, _w, h in shapes)
    width = 420
    gap_mm = 16
    scale = min((width - 2 * PAD - 12) / (big_w + gap_mm + PHONE[0]), 340 / big_h)
    area_h = big_h * scale
    single = len(keys) <= 1
    lines = 0 if single else len(keys)
    height = 64 + area_h + 30 + lines * 22 + 34

    img, d = _card(width, height, 'Paper sizes')
    total_w = (big_w + gap_mm + PHONE[0]) * scale
    left = (width - total_w) / 2
    top = 66
    d.rectangle([_p(left - 6), _p(top - 6), _p(left + big_w * scale + 6), _p(top + area_h + 6)], fill=PAGE)

    for key, w, h in sorted(shapes, key=lambda s: -(s[1] * s[2])):
        x1, y1 = left + w * scale, top + h * scale
        if key == 'A4':
            colour = SOFT
            d.rectangle([_p(left), _p(top), _p(x1), _p(y1)], fill=WHITE, outline=SOFT, width=_p(1.5))
        else:
            colour = TINTS[keys.index(key) % len(TINTS)]
            soft = tuple(int(c + (255 - c) * 0.84) for c in colour)
            d.rectangle([_p(left), _p(top), _p(x1), _p(y1)], fill=soft, outline=colour, width=_p(2))
        label, _, _, like = SIZES[key]
        tx, ty = left + 9, y1 - 9
        if single and key != 'A4':
            d.text((_p(tx), _p(ty - 30)), label, font=_font('Bold', 20), fill=colour, anchor='ld')
            d.text((_p(tx), _p(ty - 14)), _short(like), font=_font('Medium', 10), fill=INK, anchor='ld')
            d.text((_p(tx), _p(ty)), f'{_cm(w)} x {_cm(h)} cm', font=_font('Regular', 10), fill=GREY,
                   anchor='ld')
        else:
            d.text((_p(tx), _p(ty)), label, font=_font('Bold', 16 if key != 'A4' else 13),
                   fill=colour if key != 'A4' else GREY, anchor='ld')

    _phone(d, left + (big_w + gap_mm) * scale, top + area_h - PHONE[1] * scale, scale)

    y = top + area_h + 30
    if not single:
        for key in keys:
            label, w, h, like = SIZES[key]
            colour = TINTS[keys.index(key) % len(TINTS)]
            d.text((_p(PAD), _p(y)), label, font=_font('Bold', 12), fill=colour)
            d.text((_p(PAD + 44), _p(y)), f'{_short(like)} · {_cm(w)} x {_cm(h)} cm',
                   font=_font('Regular', 11), fill=INK)
            y += 22
    smaller = any(w * h < A4[0] * A4[1] for k, w, h in shapes if k not in ('A4', 'LETTER'))
    d.text((_p(PAD), _p(y + 4)),
           'Drawn to scale. Smaller sizes are printed on A4 and cut out.' if smaller else 'Drawn to scale.',
           font=_font('Regular', 10), fill=GREY)
    return _png(img)


def _short(like):
    """The everyday words, first part only: 'half of an A4 sheet'."""
    words = like.split(',')[0]
    return words[:1].upper() + words[1:]


# ── Their photo, as it will print ──────────────────────────────────────────

def _layout(w, h, sheet):
    """Where the pieces go on the sheet: (piece_w, piece_h, columns, rows), the way that fits most."""
    sw, sh = sheet
    upright = (sw // w, sh // h)
    turned = (sw // h, sh // w)
    if turned[0] * turned[1] > upright[0] * upright[1]:
        return h, w, turned[0], turned[1]
    return w, h, upright[0], upright[1]


def shape_differs(photo_w, photo_h, piece_w, piece_h, tolerance=0.05):
    """True when the photo and the piece are clearly different shapes (either way round)."""
    photo = max(photo_w, photo_h) / min(photo_w, photo_h)
    piece = max(piece_w, piece_h) / min(piece_w, piece_h)
    return abs(photo - piece) / piece > tolerance


def _place(photo, box_w, box_h, fill):
    """The photo in a box of box_w x box_h px: whole (white edges) or filling it (edges trimmed)."""
    pw, ph = photo.size
    ratio = max(box_w / pw, box_h / ph) if fill else min(box_w / pw, box_h / ph)
    size = (max(int(pw * ratio), 1), max(int(ph * ratio), 1))
    resized = photo.resize(size, Image.LANCZOS)
    box = Image.new('RGB', (box_w, box_h), WHITE)
    box.paste(resized, ((box_w - size[0]) // 2, (box_h - size[1]) // 2))
    return box


def preview(image_bytes, size, copies=1, fill=False):
    """
    The customer's photo laid out as we'd print it. Left: the sheet, as many
    pieces as fit (or as many copies as they want, if fewer), cut lines
    dotted in. Right: one piece the way they take it home, upright, a
    phone beside it. Same scale throughout. Returns (png, facts), or
    (None, {'error': ...}) when it can't be drawn.
    """
    from PIL import ImageOps, UnidentifiedImageError
    key = key_for(size)
    if key is None:
        return None, {'error': f'Not a size I know: {size}. Ask for the width and height.'}
    label, w, h, like = SIZES[key]
    if w * h > A3[0] * A3[1]:
        return None, {'error': 'Bigger than A3 is large format: hand it to a person.'}
    try:
        photo = ImageOps.exif_transpose(Image.open(BytesIO(image_bytes))).convert('RGB')
    except (UnidentifiedImageError, OSError, ValueError):
        return None, {'error': 'That file is not a photo I can open. Describe the size in words instead.'}

    sheet_key = 'A4' if (w <= A4[0] and h <= A4[1]) or (h <= A4[0] and w <= A4[1]) else 'A3'
    sheet = A4 if sheet_key == 'A4' else A3
    piece_w, piece_h, cols, rows = _layout(w, h, sheet)
    per_sheet = max(cols * rows, 1)
    copies = max(int(copies or 1), 1)
    on_this_sheet = min(copies, per_sheet)
    whole_sheet = (w, h) in (A4, A3)

    width, gap_mm = 460, 18
    piece_up = (w, h) if photo.size[0] <= photo.size[1] or w > h else (h, w)
    right_w = 0 if whole_sheet else piece_up[0] + gap_mm * 0.6 + PHONE[0]
    usable = width - 2 * PAD - 8
    scale = min(usable / (sheet[0] + (gap_mm + right_w if right_w else gap_mm + PHONE[0])), 330 / sheet[1])
    sheet_px = (sheet[0] * scale, sheet[1] * scale)
    height = 66 + 22 + sheet_px[1] + 28 + 3 * 18 + 26

    img, d = _card(width, height, 'Your print preview')
    total = sheet[0] + gap_mm + (right_w if right_w else PHONE[0])
    left = (width - total * scale) / 2
    top = 66 + 22

    # Left: the sheet as it goes through the printer.
    d.text((_p(left), _p(top - 8)), f'On one {sheet_key} sheet', font=_font('Bold', 11), fill=INK, anchor='ld')
    d.rectangle([_p(left - 5), _p(top - 5), _p(left + sheet_px[0] + 5), _p(top + sheet_px[1] + 5)], fill=PAGE)
    d.rectangle([_p(left), _p(top), _p(left + sheet_px[0]), _p(top + sheet_px[1])], fill=WHITE,
                outline=SOFT, width=_p(1))
    slot_w, slot_h = piece_w * scale, piece_h * scale
    grid_w, grid_h = cols * slot_w, rows * slot_h
    gx, gy = left + (sheet_px[0] - grid_w) / 2, top + (sheet_px[1] - grid_h) / 2
    # The photo turns with the piece, as the printer would place it.
    turned = (piece_w > piece_h) != (photo.size[0] > photo.size[1])
    on_sheet = photo.rotate(90, expand=True) if turned and not whole_sheet else photo
    tile = _place(on_sheet, max(_p(slot_w) - _p(2), 1), max(_p(slot_h) - _p(2), 1), fill)
    n = 0
    for r in range(rows):
        for c in range(cols):
            if n >= on_this_sheet:
                break
            x, y = gx + c * slot_w, gy + r * slot_h
            img.paste(tile, (_p(x) + _p(1), _p(y) + _p(1)))
            n += 1
    if not whole_sheet:
        # A cut wherever a piece has an edge, except where that edge is
        # already the edge of the sheet.
        edge = 1.5 * scale
        for c in range(cols + 1):
            x = gx + c * slot_w
            if left + edge < x < left + sheet_px[0] - edge:
                _dashed(d, (x, top), (x, top + sheet_px[1]))
        for r in range(rows + 1):
            y = gy + r * slot_h
            if top + edge < y < top + sheet_px[1] - edge:
                _dashed(d, (left, y), (left + sheet_px[0], y))

    # Right: one piece, the way they hold it, and a phone for size.
    rx = left + (sheet[0] + gap_mm) * scale
    if whole_sheet:
        _phone(d, rx, top + sheet_px[1] - PHONE[1] * scale, scale)
    else:
        pw, ph = piece_up[0] * scale, piece_up[1] * scale
        py = top + sheet_px[1] - ph
        d.text((_p(rx), _p(py - 8)), 'What you take home', font=_font('Bold', 11), fill=INK, anchor='ld')
        upright = _place(photo, _p(pw), _p(ph), fill)
        img.paste(upright, (_p(rx), _p(py)))
        d.rectangle([_p(rx), _p(py), _p(rx + pw), _p(py + ph)], outline=SOFT, width=_p(1))
        _phone(d, rx + pw + gap_mm * 0.6 * scale, top + sheet_px[1] - PHONE[1] * scale, scale)

    y = top + sheet_px[1] + 28
    sheets = math.ceil(copies / per_sheet)
    plain = _short(like)
    lines = [(f'{label} · {plain[:1].lower() + plain[1:]} · {_cm(w)} x {_cm(h)} cm', 'Bold')]
    if not whole_sheet:
        lines.append((f'{per_sheet} fit on one {sheet_key} sheet, cut along the red dotted lines'
                      if per_sheet > 1 else f'Printed on {sheet_key}, trimmed along the red dotted lines', 'Regular'))
    lines.append((f'{copies} cop{"y" if copies == 1 else "ies"} = {sheets} sheet{"s" if sheets > 1 else ""}'
                  + (' like this' if sheets > 1 else ''), 'Regular'))
    for words, weight in lines:
        d.text((_p(PAD), _p(y)), words, font=_font(weight, 11.5), fill=INK if weight == 'Bold' else GREY)
        y += 18

    differs = shape_differs(photo.size[0], photo.size[1], w, h)
    note = ('Whole photo shown, with white edges' if differs and not fill else
            'Photo fills the piece, edges trimmed' if differs else '')
    if note:
        d.text((_p(PAD), _p(y + 6)), note, font=_font('Regular', 10), fill=GREY)
    facts_out = {
        'size': label, 'sheet': sheet_key, 'fit_on_one_sheet': per_sheet, 'copies': copies,
        'sheets_needed': sheets, 'photo_shape_differs': differs,
        'shown': 'filling the piece, edges trimmed' if fill else 'the whole photo',
    }
    if differs:
        facts_out['say'] = ('The photo is a different shape from the piece: either the whole photo with white '
                            'edges, or filling the piece with its edges trimmed. If they haven\'t said, ask which '
                            'they prefer, in one short question.')
    return _png(img), facts_out
