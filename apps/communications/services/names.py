"""
What to call a customer (20 Nov 2026).

A week of chats showed receipts and thank-yous going to "The", ".", "A",
"Osekre01", "doedominic2010@gmail.com", "Nik_cage..⚓️" and "GOD". New chat
customers were registered with the first word of their WhatsApp profile name,
and every greeting trusted the record. And a customer who said "I'm not Mary"
still got "Thank you for coming back today, Mary!" that evening.

So one place decides, for every greeting Octos sends (its replies, the
counter welcome, receipts, thank-yous, reminders):

  1. a name the customer gave in this chat ("my name is Akos", "call me Akos")
  2. the customer record's first name, if it looks like a real first name
  3. otherwise no name: "Here's your receipt. Thank you…" reads fine

and a name the customer refused ("I'm not Mary") is never used again for
them. A WhatsApp username (@handle) is never a name.
"""
import re

from apps.spine import kinds

TITLES = {'mr', 'mrs', 'ms', 'mss', 'miss', 'mstr', 'master', 'dr', 'prof', 'rev', 'revd', 'pastor', 'madam',
          'mad', 'mdm', 'sir', 'hon', 'nana', 'togbe', 'apostle', 'bishop', 'eng', 'esq', 'lady', 'auntie',
          'aunty', 'uncle', 'bro', 'sis', 'mama', 'papa', 'evangelist', 'prophet', 'elder', 'deacon'}
NOT_NAMES = {
    'the', 'a', 'an', 'and', 'of', 'my', 'me', 'i', 'im', 'it', 'is', 'you', 'your', 'we', 'us', 'our', 'this',
    'hi', 'hello', 'hey', 'good', 'morning', 'yes', 'no', 'ok', 'okay', 'god', 'lord', 'jesus', 'allah', 'boss',
    'customer', 'client', 'user', 'admin', 'test', 'unknown', 'none', 'na', 'walk', 'walkin', 'guest', 'official',
    'real', 'baby', 'babe', 'love', 'queen', 'princess', 'prince', 'king', 'mummy', 'mommy', 'daddy', 'mum',
    'walk-in', 'walkin', 'whatsapp', 'farhat', 'octos', 'iphone', 'samsung', 'tecno', 'infinix', 'phone', 'home', 'work', 'office',
}
BUSINESS = re.compile(
    r'(enterprise|ventures?|limited|\bltd\b|company|\bco\b|\bshop\b|print|press|services?|solutions?|\bhub\b|'
    r'global|international|group|store|consult|agency|academy|school|church|ministr|media|studio|tech|digital|'
    r'foundation|logistics|trading|holdings|\bgh\b|ghana)', re.IGNORECASE)
WORD = re.compile(r"[^\W\d_][^\W\d_'\-]{1,14}")      # letters (any alphabet), 2 to 15, ' and - inside
LONGEST_ALONE = 12                                    # one run-together word longer than this is a handle

# "I'm not Mary", "it's Akos not Mary", "my name isn't Mary": counted only when
# the word is a name we've been using for them, so "I'm not sure" is never a correction.
NOT_ME = re.compile(r"\b(?:not|isn'?t|is not)\s+(?:called\s+)?([^\W\d_]{2,15})", re.IGNORECASE)
MY_NAME = re.compile(r"\bmy name(?:'s| is)\s+([^\W\d_]{2,15})", re.IGNORECASE)
# "call me Akos", "I'm called Akos": only a capitalised word, so "call me later" is never a name.
CALL_ME = re.compile(r"\b(?:call me|i'?m called|you can call me)\s+([^\W\d_]{2,15})", re.IGNORECASE)
NOT_AFTER_CALL = {'back', 'later', 'when', 'now', 'tomorrow', 'today', 'please', 'asap', 'again', 'once',
                  'immediately', 'soon', 'on', 'if', 'after', 'before', 'first', 'pls', 'plz', 'abeg'}


def _clean(word):
    return word.strip(".,;:!?()[]\"'")


def plausible(word):
    """The word as a first name ('Akos'), or '' when it doesn't look like one."""
    w = _clean(word or '')
    if not WORD.fullmatch(w) or w.lower() in NOT_NAMES or w.lower() in TITLES or BUSINESS.search(w):
        return ''
    if len(set(w.lower())) == 1 or re.search(r"'s$", w, re.IGNORECASE):    # "Aaaa", "PEOPLE'S"
        return ''
    return w[:1].upper() + w[1:].lower()


def first_name_from(text):
    """
    A first name from a whole name ('Mr Silas Kyeremanteg' -> 'Silas'), or ''.
    Gives up on anything that reads as a handle, an email or a business:
    'Osekre01', 'doedominic2010@gmail.com', 'Pingfenceenterprise', 'GOD'.
    """
    text = (text or '').strip()
    if not text or '@' in text or '_' in text or re.search(r'\d', text) or re.search(r'[A-Za-z]\.[A-Za-z]', text):
        return ''
    if BUSINESS.search(text):
        return ''
    words = [_clean(w) for w in text.split() if _clean(w)]
    if len(words) == 1 and len(words[0]) > LONGEST_ALONE:
        return ''
    for w in words:
        if w.lower().rstrip('.') in TITLES:
            continue
        return plausible(w)
    return ''


# ── What the customer told us ──────────────────────────────────────────────

def _events(conversation=None, customer=None):
    from django.db.models import Q
    from apps.spine.models import Event
    where = Q()
    if getattr(conversation, 'pk', None) is not None:
        where |= Q(conversation=conversation)
    if getattr(customer, 'pk', None) is not None:
        where |= Q(customer=customer)
    if not where:
        return Event.objects.none()
    return Event.objects.filter(where, kind=kinds.NAME_CORRECTED).order_by('occurred_at', 'pk')


def corrections(conversation=None, customer=None):
    """(the name they asked to be called or '', the names they refused, lowercased)."""
    preferred, refused = '', set()
    for e in _events(conversation, customer):
        if e.payload.get('refused'):
            refused.add(e.payload['refused'].lower())
            if preferred.lower() == e.payload['refused'].lower():
                preferred = ''
        if e.payload.get('preferred'):
            preferred = e.payload['preferred']
            refused.discard(preferred.lower())
    return preferred, refused


def name_for(conversation=None, customer=None, fallback=''):
    """
    What to call this customer, or ''. Their own word first, then the record's
    first name if it is a real one, then the fallback (a name typed on an
    order or receipt) if it is a real one; never a name they refused.
    """
    if customer is None and conversation is not None:
        customer = getattr(conversation, 'customer', None)
    preferred, refused = corrections(conversation, customer)
    if preferred:
        return preferred
    for whole in (_whole(customer), fallback):
        first = first_name_from(whole)
        if first and first.lower() not in refused:
            return first
    return ''


def _whole(customer):
    if customer is None:
        return ''
    return f'{getattr(customer, "first_name", "") or ""} {getattr(customer, "last_name", "") or ""}'.strip()


def for_job(job, fallback=''):
    """What to call the customer a job is for: its customer record, its chat, never a WhatsApp profile."""
    if job is None:
        return first_name_from(fallback)
    from apps.communications.services.chat_customer import chat_for
    customer = job.customer if getattr(job, 'customer_id', None) else None
    return name_for(chat_for(job), customer, fallback=fallback if customer is None else '')


def refused_any(conversation=None, customer=None):
    return bool(corrections(conversation, customer)[1])


def _names_in_use(conversation, customer):
    """The names we might have been calling them, lowercased."""
    from apps.storefront.services.accounts import find_lead
    used = {name_for(conversation, customer).lower(), first_name_from(_whole(customer)).lower(),
            ((getattr(customer, 'first_name', '') or '').split() or [''])[0].lower(),
            ((getattr(conversation, 'contact_name', '') or '').split() or [''])[0].lower()}
    phone = getattr(conversation, 'contact_phone', '')
    lead = find_lead(phone) if phone else None
    if lead is not None:
        used.add(((lead.first_name or '').split() or [''])[0].lower())
    return used - {''}


def heard(conversation, text):
    """{'refused': 'Mary'} / {'preferred': 'Akos'} / both, from what the customer wrote, or None."""
    text = text or ''
    customer = getattr(conversation, 'customer', None)
    found = {}
    for match in NOT_ME.finditer(text):
        word = _clean(match.group(1))
        if word.lower() in _names_in_use(conversation, customer):
            found['refused'] = word[:1].upper() + word[1:].lower()
            break
    named = MY_NAME.search(text)
    if named and plausible(named.group(1)):
        found['preferred'] = plausible(named.group(1))
    else:
        called = CALL_ME.search(text)
        if (called and called.group(1)[:1].isupper() and called.group(1).lower() not in NOT_AFTER_CALL
                and plausible(called.group(1))):
            found['preferred'] = plausible(called.group(1))
    if found.get('preferred', '').lower() == found.get('refused', '').lower():
        found.pop('refused', None)
    return found or None


def note_correction(conversation, message):
    """
    From the webhook: "I'm not Mary" or "my name is Akos" in a customer's
    message is remembered, on the spine, for this customer everywhere. When
    they give the name and their record's own was wrong or empty, the record
    takes it too, so the screens stop saying Mary. Returns what was heard, or None.
    """
    found = heard(conversation, getattr(message, 'body', ''))
    if not found:
        return None
    _remember(conversation, found, key=f'name:{message.pk}')
    return found


def use_name(conversation, first):
    """
    Octos was told what to call them (save_customer_name on a chat that
    already has a customer): remembered like their own word.
    """
    first = plausible(first)
    if not first:
        return ''
    _remember(conversation, {'preferred': first})
    return first


def _remember(conversation, found, key=None):
    from apps.spine.models import Event
    from apps.spine.recorder import record
    customer = getattr(conversation, 'customer', None)
    record(kinds.NAME_CORRECTED, actor=Event.CUSTOMER, conversation=conversation, customer=customer,
           key=key, payload=found,
           reason=('Not ' + found['refused'] + '. ' if found.get('refused') else '')
           + ('Wants to be called ' + found['preferred'] + '.' if found.get('preferred') else ''))
    if customer is not None and found.get('preferred'):
        current = first_name_from(_whole(customer))
        if not current or current.lower() == found.get('refused', '').lower() \
                or current.lower() in corrections(conversation, customer)[1]:
            customer.first_name = found['preferred']
            customer.save(update_fields=['first_name'])
