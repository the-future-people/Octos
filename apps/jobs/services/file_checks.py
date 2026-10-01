"""
Judging whether a file is fit to print.

`file_metadata.py` measures; this decides. The split matters: a
measurement is true whoever reads it, while a verdict depends on what
was ordered. The same 1080px photograph is good artwork on a business
card and unusable on a six-foot banner.

Three verdicts:

    fine    nothing to say
    warn    proceeds, and the acceptance is recorded so the coordinator
            sees that the customer was told rather than discovering it
    refuse  blocks the order

Thresholds follow the ordered output size rather than the service. A
banner is read from across a room and a card at arm's length, and that
is a fact about the size, not about the product — so a service nobody
has configured still gets a sensible answer.

Called before payment online, and at intake for counter work. One
implementation, or the two would disagree and the coordinator could
trust neither.
"""

FINE = 'fine'
WARN = 'warn'
REFUSE = 'refuse'

# Order matters: the worst verdict among the checks is the file's.
SEVERITY = {FINE: 0, WARN: 1, REFUSE: 2}

ACCEPTED_TYPES = {
    'application/pdf',
    'image/jpeg', 'image/jpg', 'image/png',
    'image/tiff', 'image/webp',
}

# (largest ordered edge in inches, fine at, refuse below)
# Under the fine figure but at or above the refuse figure is a warning.
RESOLUTION_BANDS = (
    # 250 rather than the traditional 300: the difference is not visible
    # on a card, and a warning that fires on good artwork stops being
    # read. The refuse figures are where print quality genuinely suffers.
    (12,    250, 150),   # cards, stickers, photographs — held at arm's length
    (36,    150, 100),   # posters, large prints — read from a few feet
    (None,   72,  50),   # banners, backdrops — read from across a room
)

# A file whose shape differs from the order by more than this is
# probably the wrong way round. Warned about, never blocked: the
# customer may have meant it, and a refusal over a crop is officious.
ASPECT_TOLERANCE = 0.25


def _band(ordered_width_in, ordered_height_in):
    longest = max(ordered_width_in or 0, ordered_height_in or 0)
    for limit, fine_at, refuse_below in RESOLUTION_BANDS:
        if limit is None or longest <= limit:
            return fine_at, refuse_below
    return RESOLUTION_BANDS[-1][1], RESOLUTION_BANDS[-1][2]


def check_file(
    metadata_state=None,
    content_type='',
    width_px=None,
    height_px=None,
    width_mm=None,
    height_mm=None,
    page_count=None,
    colour_mode='',
    pdf_images=None,
    ordered_width_in=None,
    ordered_height_in=None,
    ordered_pages=None,
    expect_cmyk=False,
):
    """
    Judge a measured file against what was ordered.

    Takes loose values rather than a JobFile, so the storefront can check
    an upload before any job exists. Returns the overall verdict and
    every check that ran, because the screen shows what passed as well as
    what did not.
    """
    from apps.jobs.models import JobFile

    checks = []

    # ── 1. Can it be opened, and is the format one we print ────────

    if metadata_state == JobFile.FAILED:
        checks.append({
            'name': 'readable',
            'verdict': REFUSE,
            'message': (
                'We could not open this file. It may be damaged, '
                'incomplete or password-protected — try sending it again.'
            ),
        })
    elif metadata_state == JobFile.UNSUPPORTED or (
        content_type and content_type not in ACCEPTED_TYPES
    ):
        # Naming the way out matters more than listing extensions at
        # someone who does not know what their file is.
        checks.append({
            'name': 'readable',
            'verdict': REFUSE,
            'message': (
                'We cannot read this kind of file. Export it as a PDF '
                'from whatever you designed it in, and send that.'
            ),
        })
    else:
        checks.append({
            'name': 'readable',
            'verdict': FINE,
            'message': 'Opens fine, and the format is one we print.',
        })

    # Nothing further can be judged on a file we could not read.
    if checks[0]['verdict'] == REFUSE:
        return {'verdict': REFUSE, 'checks': checks}

    fine_at, refuse_below = _band(ordered_width_in, ordered_height_in)

    # ── 2. Resolution at the size ordered ──────────────────────────

    effective = None
    if pdf_images is not None and content_type == 'application/pdf':
        # A PDF is judged on the worst of the images big enough to
        # matter. No images at all means vector art, which is the best
        # artwork there is — warning on it would be noise.
        meaningful = [
            i['dpi'] for i in pdf_images
            if i.get('meaningful') and i.get('dpi')
        ]
        effective = min(meaningful) if meaningful else None
    elif width_px and ordered_width_in and height_px and ordered_height_in:
        # The weaker axis is what prints badly, so it is the one judged.
        effective = int(round(min(
            width_px / ordered_width_in,
            height_px / ordered_height_in,
        )))

    if effective is None:
        checks.append({
            'name': 'resolution',
            'verdict': FINE,
            'message': 'Nothing here that loses detail when printed.',
        })
    elif effective >= fine_at:
        checks.append({
            'name': 'resolution',
            'verdict': FINE,
            'message': f'Sharp at the size you ordered ({effective} dpi).',
        })
    elif effective >= refuse_below:
        checks.append({
            'name': 'resolution',
            'verdict': WARN,
            'message': (
                f'This works out at {effective} dpi across the size you '
                f'ordered. It will print softer than usual.'
            ),
        })
    else:
        checks.append({
            'name': 'resolution',
            'verdict': REFUSE,
            'message': (
                f'This is only {effective} dpi across the size you '
                f'ordered, and would print blurred. Send a larger '
                f'version of the same artwork.'
            ),
        })

    # ── 3. Pages and shape against the order ───────────────────────

    if ordered_pages and page_count and page_count != ordered_pages:
        checks.append({
            'name': 'pages',
            'verdict': REFUSE,
            'message': (
                f'You ordered {ordered_pages} page'
                f'{"s" if ordered_pages != 1 else ""}, and this file has '
                f'{page_count}.'
            ),
        })
    else:
        checks.append({
            'name': 'pages',
            'verdict': FINE,
            'message': 'Page count matches your order.',
        })

    ordered_ratio = _ratio(ordered_width_in, ordered_height_in)
    file_ratio = _ratio(width_px, height_px) or _ratio(width_mm, height_mm)
    if ordered_ratio and file_ratio:
        drift = abs(file_ratio - ordered_ratio) / ordered_ratio
        if drift > ASPECT_TOLERANCE:
            checks.append({
                'name': 'shape',
                'verdict': WARN,
                'message': (
                    'This file is a different shape from the size you '
                    'ordered, so some of it will be cropped or there '
                    'will be space at the edges.'
                ),
            })

    # ── Warnings ───────────────────────────────────────────────────

    if expect_cmyk and colour_mode and colour_mode.upper().startswith('RGB'):
        checks.append({
            'name': 'colour',
            'verdict': WARN,
            'message': (
                'This file is in RGB. Colours may print a little '
                'differently from how they look on screen.'
            ),
        })

    worst = max(checks, key=lambda c: SEVERITY[c['verdict']])['verdict']
    return {'verdict': worst, 'checks': checks}


def _ratio(a, b):
    try:
        a, b = float(a), float(b)
    except (TypeError, ValueError):
        return None
    return a / b if a and b else None