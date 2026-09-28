"""
What an Octos PDF looks like.

Before this module, every builder defined its own colours. FARHAT_RED was
written out in four files, and the greys quietly disagreed: #1A1A1A in
two, #111111 in the weekly filing, #18181b in the branch statement.
Mid-greys ran #444444, #555555, #666666, #3f3f46. A customer holding a
proforma and an invoice was looking at two different documents.

The palette is warm rather than cool. These are printed documents from a
printing press — the customer sees them on paper, not beside the
software — and warm greys sit better against off-white stock and survive
photocopying.

Brand colours are fixed and not up for adjustment.
"""

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm


# ── Brand ─────────────────────────────────────────────────────────────

FARHAT_RED  = colors.HexColor('#E31E24')
FARHAT_GOLD = colors.HexColor('#F5A623')

# ── Greys, darkest first ──────────────────────────────────────────────

INK         = colors.HexColor('#1a1a1a')   # headings, figures, totals
BODY        = colors.HexColor('#555555')   # ordinary text
MUTED       = colors.HexColor('#999999')   # labels, footnotes, captions
BORDER      = colors.HexColor('#e0ddd8')   # rules and table lines
BG          = colors.HexColor('#f7f6f3')   # header rows, panels
BG_ALT      = colors.HexColor('#faf9f7')   # alternating table rows
WHITE       = colors.white

# ── Status colours ────────────────────────────────────────────────────
# Text and background pairs, so a flagged figure reads the same in every
# document rather than each builder inventing its own amber.

GREEN       = colors.HexColor('#1a7a4a')
GREEN_BG    = colors.HexColor('#e6f9f2')
AMBER       = colors.HexColor('#b86e00')
AMBER_BG    = colors.HexColor('#fff8e6')
BLUE        = colors.HexColor('#3355cc')
BLUE_BG     = colors.HexColor('#e8f0fe')
PURPLE      = colors.HexColor('#6b2fd4')
PURPLE_BG   = colors.HexColor('#f0e8ff')
RED_TEXT    = colors.HexColor('#cc3300')
RED_BG      = colors.HexColor('#fde8e8')

# ── Page ──────────────────────────────────────────────────────────────

MARGIN      = 20 * mm
FONT        = 'Helvetica'
FONT_BOLD   = 'Helvetica-Bold'


def style(name, size=10, bold=False, color=BODY, **kwargs):
    """
    A paragraph style with the house defaults already applied.

    Every builder was writing ParagraphStyle('x', fontSize=..,
    fontName=.., textColor=..) by hand, which is where the greys drifted
    apart in the first place.
    """
    return ParagraphStyle(
        name,
        fontSize  = size,
        fontName  = FONT_BOLD if bold else FONT,
        textColor = color,
        leading   = kwargs.pop('leading', size * 1.3),
        **kwargs,
    )


def money(amount, prefix='GHS '):
    """GHS 1,234.50 — the same everywhere, including for None."""
    return f"{prefix}{float(amount or 0):,.2f}"


def table_style(header=True, zebra=True, grid=True):
    """
    The house table: a tinted header row, alternating body rows, hairline
    rules. Returns the command list, so a builder can extend it with
    whatever that particular table needs.
    """
    commands = [
        ('FONTNAME',     (0, 0), (-1, -1), FONT),
        ('FONTSIZE',     (0, 0), (-1, -1), 9),
        ('TEXTCOLOR',    (0, 0), (-1, -1), BODY),
        ('VALIGN',       (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING',   (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 6),
        ('LEFTPADDING',  (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]
    if header:
        commands += [
            ('BACKGROUND', (0, 0), (-1, 0), BG),
            ('FONTNAME',   (0, 0), (-1, 0), FONT_BOLD),
            ('TEXTCOLOR',  (0, 0), (-1, 0), INK),
        ]
    if zebra:
        start = 1 if header else 0
        commands.append(
            ('ROWBACKGROUNDS', (0, start), (-1, -1), [WHITE, BG_ALT])
        )
    if grid:
        commands.append(('LINEBELOW', (0, 0), (-1, -1), 0.5, BORDER))
    return commands