"""
Can this file be printed as ordered? The intake coordinator's question.

For each piece: what was ordered (or is needed) beside what the file
measures, row by row, each marked by Octos rather than ticked by a person.
A row that needs attention brings its ways out: settle it (print at the
ordered size, accept no bleed, accept what could not be measured) or hold
and ask the customer.

Two checks only a person can make are signed at Clear: the text (names,
dates, numbers, spelling) and the edges (nothing important under the cut
or the eyelets). Clear is refused until every row is fine or settled and
both are signed.

Print rules (bleed, safe margin, minimum dpi) start as trade defaults by
kind of product. They move onto each product with the catalogue rebuild;
nothing that reads them changes.
"""

from decimal import Decimal

MM_PER = {'in': 25.4, 'ft': 304.8, 'cm': 10.0, 'mm': 1.0, 'm': 1000.0}
PAPER_MM = {'A3': (297, 420), 'A4': (210, 297), 'A5': (148, 210), 'A6': (105, 148), 'LETTER': (216, 279)}
AREA_UNITS = ('SQFT', 'SQM', 'SQIN', 'AREA')

# What a coordinator may settle a row with. Holding is an action, not a settlement.
SETTLEMENTS = {
    'SCALE':    'Print at the ordered size',
    'NO_BLEED': 'Print without bleed',
    'CHECKED':  'Checked by eye',
}
SIGNED_CHECKS = {
    'TEXT':  'Text read: names, dates, numbers and spelling',
    'EDGES': 'Edges checked: nothing important under the cut or eyelets',
}


# ── Print rules ──────────────────────────────────────────────

def rules_for(service):
    """Bleed, safe margin and minimum dpi for a product. Trade defaults for now."""
    name = (service.name or '').lower()
    unit = (service.unit or '').upper().replace('PER_', '')
    if 'banner' in name or 'flexy' in name or unit in AREA_UNITS:
        return {'kind': 'banner', 'bleed_mm': 0, 'safe_mm': 25, 'min_dpi': 100}
    if 'sticker' in name or 'label' in name:
        return {'kind': 'sticker', 'bleed_mm': 2, 'safe_mm': 3, 'min_dpi': 300}
    if 'dtf' in name or 'transfer' in name or 'shirt' in name or 'textile' in name:
        return {'kind': 'transfer', 'bleed_mm': 0, 'safe_mm': 2, 'min_dpi': 300}
    return {'kind': 'sheet', 'bleed_mm': 3, 'safe_mm': 5, 'min_dpi': 300}


# ── Measuring ────────────────────────────────────────────────

def _fmt(value):
    return f'{float(value):g}'


def ordered_size(line):
    """(short_mm, long_mm, label) of what was ordered, or None."""
    specs = line.specifications or {}
    for unit, mm in MM_PER.items():
        try:
            w = float(specs.get(f'width_{unit}'))
            h = float(specs.get(f'height_{unit}'))
        except (TypeError, ValueError):
            continue
        a, b = sorted((w * mm, h * mm))
        return a, b, f'{_fmt(w)} × {_fmt(h)} {unit}'
    paper = (getattr(line, 'paper_size', '') or '').upper()
    if paper in PAPER_MM:
        a, b = PAPER_MM[paper]
        return float(a), float(b), paper
    return None


def _file_for(line):
    """The file to judge this piece by: its own print file, else the job's."""
    from django.db.models import Case, IntegerField, Value, When
    from apps.jobs.models import JobFile
    order = Case(When(file_type='FINAL', then=Value(0)), When(file_type='ORIGINAL', then=Value(1)),
                 default=Value(2), output_field=IntegerField())
    own = JobFile.objects.filter(line_item=line).annotate(o=order).order_by('o', 'pk').first()
    return own or JobFile.objects.filter(job_id=line.job_id, line_item__isnull=True) \
        .annotate(o=order).order_by('o', 'pk').first()


def _close(a, b):
    return abs(a - b) <= max(2.0, 0.01 * max(a, b))


def _row(key, label, ordered, file, status, note='', fixes=()):
    return {'key': key, 'label': label, 'ordered': ordered, 'file': file,
            'status': status, 'note': note, 'fixes': list(fixes)}


# ── The comparison ───────────────────────────────────────────

def compare(job):
    """Every piece's rows, plus the two checks a person signs."""
    pieces = []
    for line in job.line_items.select_related('service').filter(parent__isnull=True).order_by('position', 'pk'):
        rules = rules_for(line.service)
        rows = []
        f = _file_for(line)
        size = ordered_size(line)
        needs_file = bool(getattr(line.service, 'requires_file_upload', False)) or line.service.category == 'PRODUCTION'

        if f is None:
            if needs_file:
                rows.append(_row('FILE', 'File', 'A print file', 'None attached', 'warn',
                                 'There is no file for this piece.', ()))
        else:
            measured = getattr(f, 'metadata_state', '') == 'MEASURED' and f.width_mm and f.height_mm
            fa = fb = None
            if measured:
                fa, fb = sorted((float(f.width_mm), float(f.height_mm)))
            file_label = (f'{_fmt(round(fb and fa / MM_PER["in"] or 0, 1))} × {_fmt(round(fb / MM_PER["in"], 1))} in'
                          if measured else '')

            # Size, and bleed beside it
            if size is None:
                rows.append(_row('SIZE', 'Size', '—', file_label or 'Not measured', 'none',
                                 'No size was ordered to compare with.', ('CHECKED',)))
            elif not measured:
                rows.append(_row('SIZE', 'Size', size[2], 'Not measured', 'none',
                                 "Octos couldn't measure this file. Check it by eye.", ('CHECKED',)))
            else:
                oa, ob, olabel = size
                bleed = rules['bleed_mm']
                exact = _close(fa, oa) and _close(fb, ob)
                with_bleed = bleed and _close(fa, oa + 2 * bleed) and _close(fb, ob + 2 * bleed)
                if exact or with_bleed:
                    rows.append(_row('SIZE', 'Size', olabel, file_label, 'ok'))
                else:
                    same_shape = abs((fa / fb) - (oa / ob)) <= 0.02
                    bigger = fa > oa
                    rows.append(_row(
                        'SIZE', 'Size', olabel, file_label, 'warn',
                        f"The file is {'bigger' if bigger else 'smaller'} than the order.",
                        ('SCALE',) if same_shape else (),
                    ))

                if bleed:
                    if with_bleed:
                        rows.append(_row('BLEED', 'Bleed', f'{bleed} mm each side', 'Included', 'ok'))
                    else:
                        rows.append(_row('BLEED', 'Bleed', f'{bleed} mm each side', 'None found', 'warn',
                                         'Without bleed, a white edge can show after cutting.', ('NO_BLEED',)))
                else:
                    rows.append(_row('BLEED', 'Bleed', 'None needed', '—', 'ok'))

            # Resolution at the ordered size
            if size and measured and f.width_px and f.height_px:
                pa, pb = sorted((f.width_px, f.height_px))
                dpi = int(min(pa / (size[0] / MM_PER['in']), pb / (size[1] / MM_PER['in'])))
                ok = dpi >= rules['min_dpi']
                rows.append(_row('RESOLUTION', 'Resolution', f"At least {rules['min_dpi']} dpi",
                                 f'{dpi:,} dpi', 'ok' if ok else 'warn',
                                 '' if ok else 'It may print soft or blocky at this size.', () if ok else ('CHECKED',)))
            elif size and measured and f.dpi:
                dpi = int(f.dpi * (fb / size[1]))
                ok = dpi >= rules['min_dpi']
                rows.append(_row('RESOLUTION', 'Resolution', f"At least {rules['min_dpi']} dpi",
                                 f'{dpi:,} dpi', 'ok' if ok else 'warn',
                                 '' if ok else 'It may print soft or blocky at this size.', () if ok else ('CHECKED',)))

            # Colour, as information
            if f.colour_mode:
                rows.append(_row('COLOUR', 'Colour', '—', f.colour_mode, 'ok'))

            # Pages
            pages = int(line.pages or 1)
            if f.page_count:
                ok = f.page_count == pages
                rows.append(_row('QUANTITY', 'Pages', f'{pages} × {line.quantity or 1}', f'{f.page_count} page'
                                 + ('' if f.page_count == 1 else 's'), 'ok' if ok else 'warn',
                                 '' if ok else "The file's pages don't match the order.", () if ok else ('CHECKED',)))

            # Edges: measured later; for now a person checks with the overlay
            rows.append(_row('EDGES', 'Edges', f"{rules['safe_mm']} mm clear", 'Check with Margins', 'sign'))

        addons = [a.service.name for a in line.addons.select_related('service')] if hasattr(line, 'addons') else []
        pieces.append({
            'line':      line.pk,
            'product':   line.service.name,
            'quantity':  line.quantity or 1,
            'finishing': addons,
            'rules':     rules,
            'file':      None if f is None else {
                'id': f.pk, 'name': (f.original_filename or f.file.name.rsplit('/', 1)[-1]),
                'size_bytes': f.size_bytes, 'content_type': f.content_type,
            },
            'rows':      rows,
        })
    return {'pieces': pieces, 'signed_checks': [{'key': k, 'label': v} for k, v in SIGNED_CHECKS.items()],
            'settlements': SETTLEMENTS}


def gate(job, signed, settled):
    """What still stands between this job and Clear. Empty means it may clear."""
    missing = []
    for piece in compare(job)['pieces']:
        for row in piece['rows']:
            if row['status'] in ('warn', 'none'):
                choice = (settled or {}).get(f"{piece['line']}:{row['key']}")
                if choice not in row['fixes']:
                    missing.append(f"settle {row['label'].lower()} on {piece['product']}")
    for key in SIGNED_CHECKS:
        if key not in (signed or []):
            missing.append('read the text' if key == 'TEXT' else 'check the edges')
    return missing


def operator_notes(job, settled):
    """What the floor must know from intake, in plain words, for the operator's card."""
    lines = []
    for piece in compare(job)['pieces']:
        size = next((r for r in piece['rows'] if r['key'] == 'SIZE'), None)
        if (settled or {}).get(f"{piece['line']}:SIZE") == 'SCALE' and size:
            lines.append(f"{piece['product']}: print at {size['ordered']} (file is {size['file']}, scale it).")
        if (settled or {}).get(f"{piece['line']}:BLEED") == 'NO_BLEED':
            lines.append(f"{piece['product']}: print without bleed, as agreed at intake.")
    return lines