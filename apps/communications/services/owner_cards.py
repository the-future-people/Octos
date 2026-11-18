"""
The owner's reports as one picture (18 Nov 2026): Octos black header with
its red rule, the big number, three tiles, then short sections. Readable at
a glance on a phone.

render() takes plain data (owner_reports builds it), so it can be checked
without a database. If drawing fails, the caller sends the words alone.

    {'kicker': 'Morning brief', 'date': 'Wednesday 18 November',
     'greeting': 'Good morning, Khofi',
     'hero': {'label': ..., 'value': 'GHS 3,240.00', 'note': '▲ 12% on Monday'},
     'tiles': [('Jobs taken', '23'), ...],
     'sections': [{'title': ..., 'rows': [(label, value)]},
                  {'title': ..., 'items': [('red'|'amber'|'green', words)]}],
     'footer': ...}
"""
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

INK = (11, 11, 12)
GREY = (96, 98, 104)
LIGHT = (140, 142, 148)
RULE = (232, 232, 229)
TILE = (245, 245, 243)
PAGE = (236, 236, 233)
WHITE = (255, 255, 255)
RED = (227, 0, 15)
UP = (21, 128, 61)
DOWN = (200, 30, 30)
DOTS = {'red': (227, 0, 15), 'amber': (232, 150, 0), 'green': (22, 163, 74)}

S = 2                    # drawn at twice the size: sharp on phones
W = 420                  # card width in points
MARGIN = 18              # page around the card
PAD = 22                 # inside the card
HEADER = 62

FONT_DIR = Path(__file__).resolve().parents[2] / 'finance' / 'assets' / 'fonts'
MARK = Path(__file__).resolve().parent.parent / 'assets' / 'octos-mark.png'


def _font(weight, size):
    return ImageFont.truetype(str(FONT_DIR / f'DMSans-{weight}.ttf'), int(size * S))


def _wrap(draw, text, font, width):
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


def _fit(draw, text, font, width):
    """One line, shortened with … if it would run past `width`."""
    text = str(text)
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + '…', font=font) > width:
        text = text[:-1]
    return text.rstrip() + '…'


def render(data) -> bytes:
    w, pad = W * S, PAD * S
    inner = w - 2 * pad
    canvas = Image.new('RGB', (w, 6000), WHITE)
    d = ImageDraw.Draw(canvas)

    # Header: Octos black, the mark, the name, what this is and when.
    d.rectangle([0, 0, w, HEADER * S], fill=INK)
    try:
        mark = Image.open(MARK).convert('RGBA').resize((34 * S, 34 * S), Image.LANCZOS)
        canvas.paste(mark, (pad - 4 * S, (HEADER * S - mark.height) // 2), mark)
        name_x = pad + 36 * S
    except Exception:
        name_x = pad
    d.text((name_x, HEADER * S // 2), 'OCTOS', font=_font(700, 17), fill=WHITE, anchor='lm')
    d.text((w - pad, HEADER * S // 2 - 8 * S), str(data.get('kicker', '')).upper(),
           font=_font(700, 10.5), fill=(255, 255, 255), anchor='rm')
    d.text((w - pad, HEADER * S // 2 + 9 * S), data.get('date', ''),
           font=_font(400, 10.5), fill=(170, 170, 170), anchor='rm')
    d.rectangle([0, HEADER * S, w, (HEADER + 3) * S], fill=RED)
    y = (HEADER + 3 + 18) * S

    if data.get('greeting'):
        d.text((pad, y), data['greeting'], font=_font(700, 15), fill=INK)
        y += 28 * S

    hero = data.get('hero') or {}
    if hero:
        d.text((pad, y), hero.get('label', ''), font=_font(500, 11), fill=GREY)
        y += 18 * S
        d.text((pad, y), hero.get('value', ''), font=_font(700, 32), fill=INK)
        y += 44 * S
        note = hero.get('note') or ''
        if note:
            up, down = note.startswith('▲'), note.startswith('▼')
            colour = UP if up else DOWN if down else GREY
            x = pad
            if up or down:
                # The font has no arrows: a small triangle, drawn.
                t, mid = 4.5 * S, y + 8 * S
                points = ([(x, mid + t), (x + 2 * t, mid + t), (x + t, mid - t)] if up
                          else [(x, mid - t), (x + 2 * t, mid - t), (x + t, mid + t)])
                d.polygon(points, fill=colour)
                x += 2 * t + 5 * S
                note = note[1:].strip()
            d.text((x, y), note, font=_font(500, 11), fill=colour)
            y += 20 * S
        y += 6 * S

    tiles = data.get('tiles') or []
    if tiles:
        gap = 8 * S
        tw = (inner - gap * (len(tiles) - 1)) // len(tiles)
        th = 54 * S
        for i, (label, value) in enumerate(tiles):
            x = pad + i * (tw + gap)
            d.rounded_rectangle([x, y, x + tw, y + th], radius=10 * S, fill=TILE)
            d.text((x + 12 * S, y + 10 * S), str(value), font=_font(700, 18), fill=INK)
            d.text((x + 12 * S, y + 35 * S), _fit(d, label, _font(500, 10), tw - 20 * S),
                   font=_font(500, 10), fill=GREY)
        y += th + 20 * S

    for section in data.get('sections') or []:
        d.text((pad, y), str(section.get('title', '')).upper(), font=_font(700, 9.5), fill=LIGHT)
        y += 18 * S
        for label, value in section.get('rows') or []:
            vf = _font(700, 12)
            vw = d.textlength(str(value), font=vf)
            d.text((pad, y), _fit(d, label, _font(400, 12), inner - vw - 16 * S), font=_font(400, 12), fill=INK)
            d.text((w - pad, y), str(value), font=vf, fill=INK, anchor='ra')
            y += 22 * S
            d.line([pad, y - 5 * S, w - pad, y - 5 * S], fill=RULE, width=S)
        for level, words in section.get('items') or []:
            f = _font(400, 12)
            lines = _wrap(d, words, f, inner - 16 * S)
            r = 3.5 * S
            cy = y + 9 * S
            d.ellipse([pad, cy - r, pad + 2 * r, cy + r], fill=DOTS.get(level, GREY))
            for line in lines:
                d.text((pad + 16 * S, y), line, font=f, fill=INK)
                y += 18 * S
            y += 4 * S
        y += 12 * S

    footer = data.get('footer') or ''
    if footer:
        d.line([pad, y, w - pad, y], fill=RULE, width=S)
        y += 12 * S
        d.text((w // 2, y), footer, font=_font(400, 10.5), fill=LIGHT, anchor='ma')
        y += 22 * S
    y += 6 * S

    card = canvas.crop((0, 0, w, y))
    mask = Image.new('L', card.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, card.width - 1, card.height - 1], radius=16 * S, fill=255)
    page = Image.new('RGB', (w + 2 * MARGIN * S, y + 2 * MARGIN * S), PAGE)
    page.paste(card, (MARGIN * S, MARGIN * S), mask)
    out = BytesIO()
    page.save(out, format='PNG', optimize=True)
    return out.getvalue()
