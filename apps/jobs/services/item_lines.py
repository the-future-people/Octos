"""
How a job's items are described: one way, everywhere (13 Nov 2026).

The payment modal, the printed receipt and the WhatsApp receipt all describe
items through here, so they can never disagree about the same item.

  number     1, 2, 3 for the things the customer ordered; an add-on (binding,
             lamination, an envelope) sits under its item with no number
  name       the service, with its paper size when the name has none
  count      "13 pages × 2 copies", "11 pages", "12" (pages, sets = copies,
             quantity = pieces, as JobLineItem documents them)
  tags       the choices: Colour or B&W and one side or two sides (always,
             for page work only, since is_color defaults to False on
             everything), then finishes from specifications.
  sum        "13 pages × 2 copies × GHS 2.00", shown only when it really
             equals the line total: a receipt never shows arithmetic that
             does not add up to the price charged.
"""
import re
from decimal import Decimal

SIZES = ('A0', 'A1', 'A2', 'A3', 'A4', 'A5', 'A6')
SIDES = {'SINGLE': 'One side', 'DOUBLE': 'Two sides'}
# A name's own "(one side)" style note, dropped when the tag says it.
SIDE_NOTE = re.compile(r'\s*\((one|single|two|double|both)[\s-]*sided?s?\)\s*', re.I)


def _plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def _money(v):
    return f"{Decimal(v or 0):.2f}"


def is_page_work(li):
    """Pages are a declared part of this service (the signal _reconcile_pages uses)."""
    template = getattr(li.service, 'spec_template', None) or {}
    if isinstance(template, dict):
        declared = 'pages' in template or 'pages' in (template.get('fields') or [])
    else:
        declared = any(t == 'pages' or (isinstance(t, dict) and 'pages' in (t.get('key'), t.get('name')))
                       for t in template)
    return declared or (li.pages or 1) > 1 or (li.sets or 1) > 1


def describe(li, number=None):
    """One item, as every screen and receipt shows it."""
    page_work = is_page_work(li)
    name = li.service.name
    if page_work:
        name = SIDE_NOTE.sub(' ', name).strip()
    # Paper size only means something for page work: paper_size defaults to
    # A4 on every item, envelopes and binding included.
    has_size = any(s in name.upper() for s in SIZES)
    size = (li.paper_size or '').strip()
    if page_work and size and size.upper() not in ('', 'NA') and not has_size:
        name = f"{size} {name}"

    pages, sets, qty = li.pages or 1, li.sets or 1, li.quantity or 1
    if page_work:
        count = _plural(pages, 'page') + (f" × {_plural(sets, 'copy').replace('copys', 'copies')}" if sets > 1 else '')
        units = pages * sets
    else:
        count = str(qty)
        units = qty

    tags = []
    if page_work:
        # Colour mode and sides always, side by side under the breakdown: a
        # fixed column of facts the cashier never has to read the name for.
        tags.append('Colour' if li.is_color else 'B&W')
        if li.sides in SIDES:
            tags.append(SIDES[li.sides])
    for key, value in (li.specifications or {}).items():
        if key == 'pages' or value in (None, '', True, False) or isinstance(value, (int, float, list, dict)):
            continue
        text = str(value).replace('_', ' ').strip()
        text = text[:1].upper() + text[1:]
        # Each fact once: not a tag the name or another tag already says.
        if text and not text.isdigit() and text.upper() not in name.upper() and text not in tags:
            tags.append(text)

    unit = Decimal(li.unit_price or 0)
    total = Decimal(li.line_total or 0)
    adds_up = unit > 0 and (unit * units).quantize(Decimal('0.01')) == total.quantize(Decimal('0.01'))
    if adds_up and units > 1:
        sum_text = f"{count} × GHS {_money(unit)}"
    elif adds_up:
        sum_text = f"1 × GHS {_money(unit)}"
    else:
        sum_text = ''

    return {
        'number': number,
        'name': name,
        'count': count,
        'tags': tags,
        'sum': sum_text,
        'amount': _money(total),
        'is_addon': bool(getattr(li, 'parent_id', None)),
    }


def describe_job(items):
    """
    A job's items in order, numbered; each add-on directly under its item.
    Takes the job's line items (any iterable), already ordered by position.
    """
    items = list(items)
    tops = [li for li in items if not getattr(li, 'parent_id', None)]
    addons = {}
    for li in items:
        if getattr(li, 'parent_id', None):
            addons.setdefault(li.parent_id, []).append(li)
    out = []
    for n, li in enumerate(tops, 1):
        out.append(describe(li, n))
        out.extend(describe(a) for a in addons.pop(li.pk, []))
    for orphans in addons.values():                 # an add-on whose item is not in the list
        out.extend(describe(a) for a in orphans)
    return out


def _plain(text):
    """Thermal printers often lack × and ·: plain characters on paper."""
    return text.replace('×', 'x').replace('·', '-').replace('—', '-')


def thermal(items, width):
    """The numbered item block for the printed receipt, `width` characters a line."""
    rows = describe_job(items)
    if not rows:
        return []
    tops = sum(1 for r in rows if not r['is_addon'])
    out = [_plural(tops, 'item'), '']

    def line(left, right=''):
        left = _plain(left)
        room = width - len(right) - 1
        if len(left) > room:
            left = left[:room]
        return f"{left}{' ' * (width - len(left) - len(right))}{right}" if right else left

    def heading(left, right, indent):
        # A long name wraps by whole words onto the next lines; the amount
        # stays on the first. Never cut mid-word on a receipt. The indent
        # counts toward the width, so nothing is trimmed afterwards.
        lead = left[: len(left) - len(left.lstrip(' '))]
        words = _plain(left.strip()).split()
        room = width - len(right) - 1 - len(lead)
        first, rest = '', []
        for w in words:
            if not rest and len(f"{first} {w}".strip()) <= room:
                first = f"{first} {w}".strip()
            elif rest and len(f"{rest[-1]} {w}") <= width:
                rest[-1] = f"{rest[-1]} {w}"
            else:
                rest.append(f"{indent}{w}")
        return [line(lead + first, right)] + [line(r_) for r_ in rest]

    def choices_of(r):
        text = ', '.join(t.lower() if t in ('Colour', 'One side', 'Two sides') else t for t in r['tags'])
        return text[:1].upper() + text[1:] if text else ''

    # The same order as the payment modal: the item and its amount, then its
    # breakdown, then its choices (13 Nov 2026).
    for i, r in enumerate(rows):
        detail = r['sum'] or (r['count'] if r['count'] != '1' else '')
        if r['is_addon']:
            out.extend(heading(f"   + {r['name']}", r['amount'], '     '))
            indent = '     '
        else:
            if i:
                out.append('')
            out.extend(heading(f"{r['number']}. {r['name']}", r['amount'], '   '))
            indent = '   '
        if detail:
            out.append(line(f"{indent}{detail.replace('GHS ', '')}"))
        if r['tags']:
            out.append(line(f"{indent}{choices_of(r)}"))
    return out


def whatsapp(items):
    """The numbered item list for the WhatsApp receipt."""
    out = []
    for r in describe_job(items):
        choices = ', '.join(r['tags'])
        if r['is_addon']:
            out.append(f"     + {r['name']}{f' ({choices})' if choices else ''} — GHS {r['amount']}")
            continue
        out.append(f"  {r['number']}. {r['name']}{f' · {choices}' if choices else ''} — GHS {r['amount']}")
        detail = r['sum'] or (r['count'] if r['count'] != '1' else '')
        if detail:
            out.append(f"     {detail}")
    return out
