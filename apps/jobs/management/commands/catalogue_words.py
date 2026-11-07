"""
Names and descriptions, from the interview with Khofi (7 Nov 2026).

    python manage.py catalogue_words           shows what would change, saves nothing
    python manage.py catalogue_words --apply   makes the changes, all or nothing

Names fit how customers in Ghana speak (colour, photocopy, passport
picture, complimentary cards) and are the same for customers, Octos,
staff and receipts. Descriptions never carry prices: prices come only
from the price list, so the two can never disagree.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

PAPER = 'Double A 80 gsm paper'
SHEETS = 'Priced per sheet: a 10-page document is 5 sheets (an odd page count rounds up).'


def _print(size, colour, both):
    return (f'Printing your file on {size} {PAPER}, in {colour}, on {"both sides" if both else "one side"}. '
            + (SHEETS if both else 'Priced per sheet.'))


def _copy(size, colour, both):
    return (f'Photocopying a paper original you bring to the counter, on {size} {PAPER}, in {colour}, '
            f'{"both sides" if both else "one side"}. ' + (SHEETS if both else 'Priced per sheet.'))


DESIGN = 'Customers usually bring a finished design.'
FLYER = ('{size} flyers printed in colour on art paper, {sides}. Minimum 10 pieces. '
         'Black and white is possible on request. ' + DESIGN)
PASSPORT = ('A set of {n} printed passport pictures (passport photos), {kind} ({size}). Priced per set: one set is {n} pictures. '
            'Digital copies are done at the front desk only.')

WORDS = {
    # Printing
    'A4-BW-PRINT-1S': ('A4 Black & White Printing (one side)', _print('A4', 'black and white', False)),
    'A4-BW-PRINT-2S': ('A4 Black & White Printing (both sides)', _print('A4', 'black and white', True)),
    'A4-COL-PRINT-1S': ('A4 Colour Printing (one side)', _print('A4', 'colour', False)),
    'A4CLRP2': ('A4 Colour Printing (both sides)', _print('A4', 'colour', True)),
    'A3-BW-PRINT': ('A3 Black & White Printing (one side)', _print('A3', 'black and white', False)),
    'A3BWP2': ('A3 Black & White Printing (both sides)', _print('A3', 'black and white', True)),
    'A3-COL-PRINT': ('A3 Colour Printing (one side)', _print('A3', 'colour', False)),
    'A3CLRP2': ('A3 Colour Printing (both sides)', _print('A3', 'colour', True)),
    # Photocopies
    'A4-BW-COPY-1S': ('A4 Black & White Photocopy (one side)', _copy('A4', 'black and white', False)),
    'A4-BW-COPY-2S': ('A4 Black & White Photocopy (both sides)', _copy('A4', 'black and white', True)),
    'A4-COL-COPY-1S': ('A4 Colour Photocopy (one side)', _copy('A4', 'colour', False)),
    'A4CLRC2': ('A4 Colour Photocopy (both sides)', _copy('A4', 'colour', True)),
    'A3-BW-COPY': ('A3 Black & White Photocopy (one side)', _copy('A3', 'black and white', False)),
    'A3BWC2': ('A3 Black & White Photocopy (both sides)', _copy('A3', 'black and white', True)),
    'A3-COL-COPY': ('A3 Colour Photocopy (one side)', _copy('A3', 'colour', False)),
    'A3CLRC2': ('A3 Colour Photocopy (both sides)', _copy('A3', 'colour', True)),
    # Cards and certificates
    'A3-ART-CARD-1-SIDED': ('A3 Art Card Printing (one side)',
        'Printing on A3 art card (170 to 250 gsm), one side: a heavy card with a light gloss. Used for '
        'certificates, invitations and similar pieces. ' + DESIGN),
    'A3-ART-PAPER-2-SIDED': ('A3 Art Paper Printing (both sides)',
        'Printing on A3 art paper, both sides: thinner than art card, with a smooth finish. Mostly used '
        'for flyers. ' + DESIGN),
    'A4AC1': ('A4 Art Card Certificate (one side)',
        'An A4 certificate on art card (170 to 250 gsm), one side: the same heavy card as A3 Art Card, '
        'smaller. Customers usually bring the finished certificate design.'),
    'A4AC2': ('A4 Art Card Certificate (both sides)',
        'An A4 certificate on art card (170 to 250 gsm), printed on both sides: the same heavy card as '
        'A3 Art Card, smaller. ' + DESIGN),
    'A4SC1': ('A4 Shiny Certificate (one side)',
        'An A4 certificate on shiny certificate paper, one side: a shimmering finish, thinner than art '
        'card but thicker than regular paper. ' + DESIGN),
    'A4SC2': ('A4 Shiny Certificate (both sides)',
        'An A4 certificate on shiny certificate paper, printed on both sides: a shimmering finish, '
        'thinner than art card but thicker than regular paper. ' + DESIGN),
    # Flyers
    'A4-FLYER': ('A4 Flyers (one side)', FLYER.format(size='A4', sides='one side')),
    'A4-FLYER-2-SIDED': ('A4 Flyers (both sides)', FLYER.format(size='A4', sides='both sides')),
    'A5-FLYER': ('A5 Flyers (one side)', FLYER.format(size='A5 (half of A4)', sides='one side')),
    'A5-FLYER-2SIDED': ('A5 Flyers (both sides)', FLYER.format(size='A5 (half of A4)', sides='both sides')),
    # Scanning
    'A4-SCAN': ('A4 Scanning',
        'Scanning A4 pages, sent to you by WhatsApp, email or Telegram, or saved to your flash drive. '
        'Priced per page.'),
    'A3-SCAN': ('A3 Scanning',
        'Scanning A3 pages, sent to you by WhatsApp, email or Telegram, or saved to your flash drive. '
        'Priced per page.'),
    # Envelopes
    'A4-ENV': ('A4 Brown Envelope', 'An A4 brown envelope, bought on its own, with nothing printed on it.'),
    'A3-ENV': ('A3 Brown Envelope', 'An A3 brown envelope, bought on its own, with nothing printed on it.'),
    'A5-BROWN-ENVELOPE': ('A5 Brown Envelope', 'An A5 brown envelope, bought on its own, with nothing printed on it.'),
    'ENV-PACK-A4': ('A4 Brown Envelope (packed with your order)',
        'An A4 brown envelope to pack your order in: one for all copies unless you ask for one each.'),
    'ENV-PACK-A3': ('A3 Brown Envelope (packed with your order)',
        'An A3 brown envelope to pack your order in: one for all copies unless you ask for one each.'),
    'DL-ENVELOPE-PRINTING': ('Envelope Printing (DL)',
        'Printing on DL envelopes (110 x 220 mm), usually envelopes you bring; we can supply them too. '
        'Priced per envelope.'),
    # Lamination
    'A3-LAMINATION---C.F-': ('A3 Lamination (your own pouch)',
        "A3 lamination with your own pouch: you bring it, we laminate. Done at the front desk."),
    # Photos
    'PHOTO-PRINTING': ('Photo Printing (4 x 6 in)', 'A photo print, 4 x 6 inches (100 x 148 mm). Priced per print.'),
    'PP-US': ('Passport Picture (American)', PASSPORT.format(n=4, kind='American size', size='2 x 2 in')),
    'PP-BR': ('Passport Picture (Regular / British)',
              PASSPORT.format(n=8, kind='the regular size, also the British size', size='35.5 x 45.5 mm')),
    'PP-CA': ('Passport Picture (Canadian)', PASSPORT.format(n=2, kind='Canadian size', size='50 x 70 mm')),
    # Services at the counter
    'TYPING': ('Typing',
        'Typing your document from a handwritten or printed original, priced per page (less per page for '
        'long documents). Every typing job includes one printed copy of the typed document and a brown '
        'envelope; further copies are priced as printing.'),
    'FORMS-AND-FILING': ('Form Filling',
        'An attendant sits with you and fills in forms: university applications, passport forms and '
        'similar. Priced per form.'),
    # Production
    'BIZ-CARDS': ('Complimentary Cards (Business Cards)', None),
    'SAV': ('Sticker (SAV)', None),
    'SAV-CUT': ('Sticker cutting (to shape)', None),
    'EYELETS': ('Eyelets', 'Metal eyelets punched into a banner for hanging it up. Free with banners.'),
}


class Command(BaseCommand):
    help = 'Names and descriptions from the 7 Nov 2026 interview (dry run unless --apply).'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Save the changes.')

    def handle(self, *args, apply=False, **options):
        from apps.jobs.models import PricingRule, Service
        changed = 0
        with transaction.atomic():
            for code, (name, description) in WORDS.items():
                s = Service.objects.filter(code=code).first()
                if s is None:
                    self.stdout.write(f'  {code}: not in this catalogue, skipped')
                    continue
                fields = []
                if name and s.name != name:
                    self.stdout.write(f'  {code}: "{s.name}" -> "{name}"')
                    s.name = name
                    fields.append('name')
                    if s.display_name:
                        s.display_name = name
                        fields.append('display_name')
                if description and s.description != description:
                    s.description = description
                    fields.append('description')
                    self.stdout.write(f'  {code}: description: {description[:90]}...')
                if fields:
                    s.save(update_fields=fields)
                    changed += 1
            typing = PricingRule.objects.filter(service__code='TYPING', is_active=True).first()
            if typing:
                self.stdout.write(f'\nFor checking: Typing is GHS {typing.base_price} a page, tiers {typing.pricing_tiers}')
            if not changed:
                self.stdout.write('Nothing to change: the names and descriptions are as decided.')
            if apply:
                self.stdout.write(f'\nApplied: {changed} service(s) updated.')
            else:
                transaction.set_rollback(True)
                self.stdout.write(f'\nDry run: {changed} service(s) would change, nothing saved. Run with --apply.')
