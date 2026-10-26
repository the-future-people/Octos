"""
Recognising people by their names, the way names are actually written.

Shared by everything that decides whether two records are the same
person: the contacts report, linking leads to customers, merging
duplicates. One rule, so they never disagree.

- Titles are not names: Mr, Mrs, Dr, Rev, Pastor, Nana and the rest are
  set aside before anything is compared.
- Names are compared as a set of words, in any order: Ghanaian names are
  often written with the family name first, last or in the middle, so
  "Maame Frimpomaa Amoh" and "Frimpomaa Maame Amoh" are the same name.
- A shorter name agrees with a fuller one when every word of it is in
  the fuller: "Eric" with "Eric Nii Nortey", "James" with "James Mensah".
  Online, people often give one name; at the counter, all of them.
- Otherwise the names disagree. Two people on one number with different
  names is what a shared line looks like, and they are never merged.
"""

import re
import unicodedata

TITLES = {
    'mr', 'mrs', 'ms', 'miss', 'mx', 'master', 'madam', 'dr', 'doctor', 'prof', 'professor',
    'rev', 'reverend', 'pastor', 'apostle', 'bishop', 'evangelist', 'prophet', 'prophetess',
    'elder', 'deacon', 'deaconess', 'fr', 'father', 'sister', 'sr', 'brother', 'bro',
    'eng', 'engr', 'engineer', 'hon', 'honourable', 'honorable', 'lawyer', 'barrister', 'esq',
    'nana', 'togbe', 'naa', 'nii', 'oheneba', 'alhaji', 'alhaja', 'hajia', 'sheikh', 'imam',
    'chief', 'capt', 'captain', 'col', 'gen', 'lt', 'sgt', 'jnr', 'jr', 'snr', 'sr.', 'sir',
}
# "Nii", "Naa" and "Nana" are titles, but also part of many given names
# ("Eric Nii Nortey"). Set aside only at the very front of a name.
FRONT_ONLY = {'nana', 'nii', 'naa', 'togbe', 'oheneba'}


def _plain(text):
    text = unicodedata.normalize('NFKD', str(text or ''))
    text = ''.join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z' -]", ' ', text.lower())


def name_words(name):
    """The words of a name that identify the person: no titles, no punctuation."""
    words = [w.strip("'-") for w in _plain(name).split()]
    words = [w for w in words if w]
    out = []
    for i, w in enumerate(words):
        if w in TITLES and (w not in FRONT_ONLY or not out):
            continue
        out.append(w)
    return out


def names_agree(a, b):
    """
    Whether two names can be the same person: every word of the shorter
    is in the fuller, in any order. A blank name agrees with nothing.
    """
    wa, wb = set(name_words(a)), set(name_words(b))
    if not wa or not wb:
        return False
    return wa <= wb or wb <= wa