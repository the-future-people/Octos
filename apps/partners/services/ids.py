"""
Partner IDs (23 Nov 2026): the area a shop is in, then a random code.
MAD-K7Q2, printed and said as MAD·K7Q2.

Random rather than counted, so an ID never tells anyone how many partners
Farhat has. Given once, at approval, and never changed, even if the shop
moves: it is on their labels and in their customers' minds.
"""
import re
import secrets

# Letters and digits that can't be misread off a label: no I, O, 1 or 0.
ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'

# The towns partners are likeliest to be in, with the codes people would
# recognise. Anywhere else takes the first three letters of its name.
AREAS = {
    'accra': 'ACC', 'madina': 'MAD', 'kasoa': 'KAS', 'tema': 'TEM', 'adenta': 'ADT',
    'east legon': 'ELG', 'legon': 'LEG', 'dansoman': 'DAN', 'kaneshie': 'KAN', 'achimota': 'ACH',
    'lapaz': 'LPZ', 'dome': 'DOM', 'haatso': 'HAT', 'ashaiman': 'ASH', 'spintex': 'SPX',
    'teshie': 'TSH', 'nungua': 'NUN', 'osu': 'OSU', 'kwashieman': 'KWS', 'weija': 'WEJ',
    'amasaman': 'AMS', 'kumasi': 'KSI', 'takoradi': 'TKD', 'cape coast': 'CPC', 'koforidua': 'KOF',
    'ho': 'HOO', 'tamale': 'TML', 'sunyani': 'SNY', 'westland': 'WLD', 'west legon': 'WLG',
}


def area_code(area):
    """'Madina' -> 'MAD'; 'Abokobi' -> 'ABO'."""
    name = re.sub(r'\s+', ' ', (area or '').strip().lower())
    if name in AREAS:
        return AREAS[name]
    letters = re.sub(r'[^a-z]', '', name).upper()
    return (letters[:3] or 'GHA').ljust(3, 'X')


def new_code(area):
    """A fresh, unused ID for a shop in this area."""
    from apps.partners.models import Partner
    stem = area_code(area)
    while True:
        code = f"{stem}-{''.join(secrets.choice(ALPHABET) for _ in range(4))}"
        if not Partner.objects.filter(code=code).exists():
            return code
