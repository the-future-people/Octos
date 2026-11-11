"""
The presence belief (Layer 2, Step 2.2, 11 Nov 2026).

Is the customer at the counter right now? Not a switch with a timer, but a
probability, worked out fresh for each message from three things:

  1. The anchor: the strongest recent proof, with a starting belief P0
     (the attendant's tap 0.99, a signed QR 0.97, "I'm at the counter" 0.90,
     a person opened their file 0.85; no proof 0.40 while open, 0.02 closed).
  2. Time: people leave counters. P(t) = P0 * exp(-t / TAU), TAU = 25 minutes.
     This is the solution of dP/dt = -P / TAU: the belief fades in proportion
     to itself, like cooling tea.
  3. The message's texture, by Bayes' rule in log-odds form: each texture has
     a likelihood ratio (how much more likely it is from someone at the
     counter than from someone away), and the odds are multiplied by it.

Then the decision bands: at least AT_COUNTER_FROM is at the counter, at most
AWAY_TO is away, and between them Octos is honestly not sure.

texture() reads the message with plain word patterns for now. It is the only
place that reads words, so a language model can take over the reading later
without anything else changing.
"""
import math
import re
from dataclasses import dataclass, field
from datetime import timedelta

TAU_MINUTES = 25.0
LOOK_BACK = timedelta(hours=3)

ANCHOR_PRIOR = {'claimed': 0.99, 'signed_qr': 0.97, 'phrase': 0.90, 'opened': 0.85}
NO_ANCHOR_OPEN = 0.40
SHOP_CLOSED = 0.02

LIKELIHOOD = {
    'file_no_words': 2.5,     # people hand files over at the counter
    'greeting': 1.0,          # tells us nothing either way
    'words': 0.5,             # a statement: slightly more like someone away
    'info_question': 0.2,     # they would just ask the attendant
    'status_question': 0.2,   # "is it ready?": asked from elsewhere
    'on_the_way': 0.3,        # not at the counter yet
}
AFTER_OUTCOME = 0.3           # a job made or paid since the anchor: likely leaving

AT_COUNTER_FROM, AWAY_TO = 0.70, 0.30
AT_COUNTER, AWAY, UNSURE = 'AT_COUNTER', 'AWAY', 'UNSURE'

GREETING = re.compile(r"^\W*(hi+|hello+|hey+|good (morning|afternoon|evening)|morning|afternoon|evening)"
                      r"( farhat| there| everyone| all)?\W*$", re.IGNORECASE)
STATUS = re.compile(r"\b(ready|my order|my job|collect(ed)?|picked up|done yet|how much was|track)\b",
                    re.IGNORECASE)
QUESTION = re.compile(r"\?"
                      r"|^\W*(?:(?:hi+|hello+|hey+|good \w+)\W+)?(?:please\s+)?"
                      r"(do|does|can|could|how|what|where|when|which|who|is|are|will|would)\b"
                      r"|\b(do|does|can|could) (you|u|ya|y'all)\b",
                      re.IGNORECASE)
ON_THE_WAY = re.compile(r"\b(on my way|coming|outside|almost there|nearby|i'?m near|reaching)\b", re.IGNORECASE)


@dataclass
class Belief:
    p: float
    band: str
    texture: str
    reasons: list = field(default_factory=list)

    @property
    def why(self):
        return f'p={self.p:.2f}: ' + '; '.join(self.reasons)


def texture(message):
    """What kind of message this is, for the belief. The one place words are read."""
    from apps.communications.assistant import counter
    if counter.file_only(message) or (counter.no_words(message) and message.message_type in counter.MEDIA):
        return 'file_no_words'
    body = (message.body or '').strip()
    if not counter.has_words(body):
        return 'greeting'                      # an emoji, a dot: nothing to read
    if GREETING.match(body):
        return 'greeting'
    if ON_THE_WAY.search(body):
        return 'on_the_way'
    if STATUS.search(body):
        return 'status_question'
    if QUESTION.search(body):
        return 'info_question'
    return 'words'


def _odds(p):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return p / (1 - p)


def believe(anchor, minutes_since, kind, outcome_since=False, shop_open=True):
    """
    The belief from its ingredients. Pure arithmetic: no database, so it can be
    tested and explained line by line.
    """
    reasons = []
    if anchor in ANCHOR_PRIOR:
        p0 = ANCHOR_PRIOR[anchor]
        p = p0 * math.exp(-max(minutes_since, 0.0) / TAU_MINUTES)
        reasons.append(f'{anchor.replace("_", " ")} {minutes_since:.0f} min ago')
    elif shop_open:
        p = NO_ANCHOR_OPEN
        reasons.append('no proof, shop open')
    else:
        p = SHOP_CLOSED
        reasons.append('shop closed')

    odds = _odds(p)
    ratio = LIKELIHOOD.get(kind, 1.0)
    odds *= ratio
    reasons.append(kind.replace('_', ' '))
    if outcome_since:
        odds *= AFTER_OUTCOME
        reasons.append('a job made or paid since')

    p = odds / (1 + odds)
    band = AT_COUNTER if p >= AT_COUNTER_FROM else AWAY if p <= AWAY_TO else UNSURE
    return Belief(p=p, band=band, texture=kind, reasons=reasons)


def for_message(conversation, message, now, shop_open):
    """The belief for this message, from the spine's record of the conversation."""
    from apps.spine import kinds
    from apps.spine.models import Event

    anchor_event = (Event.objects
                    .filter(conversation=conversation,
                            kind__in=[kinds.PRESENCE_COUNTER, kinds.COUNTER_CLAIMED, kinds.FILE_OPENED],
                            occurred_at__gte=now - LOOK_BACK, occurred_at__lte=now)
                    .order_by('-occurred_at').first())
    anchor, minutes, since = None, 0.0, None
    if anchor_event is not None:
        since = anchor_event.occurred_at
        if anchor_event.kind == kinds.COUNTER_CLAIMED:
            anchor = 'claimed'
        elif anchor_event.kind == kinds.FILE_OPENED:
            anchor = 'opened'                  # a person has their files
        else:
            anchor = 'signed_qr' if anchor_event.payload.get('verified') else 'phrase'
    else:
        # An older counter visit with no event (before the spine): its window
        # still counts as a spoken "I'm at the counter".
        from apps.communications.assistant import counter
        until = getattr(conversation, 'counter_until', None)
        if until and until > now:
            anchor, since = 'phrase', until - counter.VISIT
    if since is not None:
        minutes = (now - since).total_seconds() / 60

    outcome = bool(since) and Event.objects.filter(
        conversation=conversation, occurred_at__gt=since, occurred_at__lte=now,
        kind__in=[kinds.JOB_CREATED, kinds.JOB_PAID, kinds.JOB_DEPOSIT_PAID, kinds.PAYMENT_SUCCEEDED],
    ).exists()
    return believe(anchor, minutes, texture(message), outcome, shop_open)
