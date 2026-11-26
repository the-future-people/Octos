"""
The checker: Octos may not state a figure it didn't get from the floor.

Before any reply is sent, every price, clock time and job reference in it
must appear in what the tools returned during that same run. One that
doesn't, and the reply is blocked; a person is brought in instead.

Tolerant of phrasing, strict on substance: "GHS 30", "30 cedis" and
"GH₵30.00" are all 30; "8am", "8:00 am" and "8:00AM" are all 8:00am. But
GHS 35 where the tools said 30 is always blocked.
"""
import re
from decimal import Decimal, InvalidOperation

# An amount starts with a digit. Before 19 Nov 2026 it could start with a
# comma, so in "Sorry, GHS 9,999.00" the comma after "Sorry" swallowed the
# "GHS" as an amount of its own and the real figure was never checked.
MONEY = re.compile(
    r'(?:GHS|GH₵|GHC|₵)\s*(\d[\d,]*(?:\.\d{1,2})?)'
    r'|(\d[\d,]*(?:\.\d{1,2})?)\s*(?:cedis?|ghs)\b',
    re.IGNORECASE,
)
TIME = re.compile(r'\b(\d{1,2})(?::(\d{2}))?\s*([ap])\.?\s?m\b\.?', re.IGNORECASE)
REF = re.compile(r'\bref(?:erence)?\.?\s*(?:no\.?\s*)?#?\s*(\d{2,})\b', re.IGNORECASE)
# A pickup code (24 Nov 2026): a wrong one sends a customer to the counter
# with a number nobody has.
CODE = re.compile(r'\bcode(?:\s+is)?\s*:?\s*(\d{4,6})\b', re.IGNORECASE)
# A job by its short number (26 Nov 2026): "#5286", "job 5286". Jobs are
# now named that way, so a wrong one points at somebody else's job.
JOB = re.compile(r'(?:(?<![\w&])#|\bjob\s+(?:no\.?\s*|number\s*)?#?)(\d{3,6})\b', re.IGNORECASE)


def unverified(reply, facts):
    """
    The figures in the reply that the facts don't contain, as readable
    strings ("GHS 35.00", "4:00pm", "ref 912"). Empty means it may be sent.

    facts is everything the tools returned in this run, as one string.
    """
    problems = []
    known_money = _money(facts)
    for amount in sorted(_money(reply) - known_money):
        problems.append(f'GHS {amount}')
    known_times = _times(facts)
    for clock in sorted(_times(reply) - known_times):
        problems.append(clock)
    for ref in sorted(set(REF.findall(reply))):
        if ref not in facts:
            problems.append(f'ref {ref}')
    for job in sorted(set(JOB.findall(reply))):
        if job not in (facts or ''):
            problems.append(f'job #{job}')
    for code in sorted(set(CODE.findall(reply))):
        if not re.search(rf'\b{code}\b', facts or ''):
            problems.append(f'code {code}')
    return problems


def _money(text):
    amounts = set()
    for a, b in MONEY.findall(text or ''):
        raw = (a or b).replace(',', '')
        try:
            amounts.add(f'{Decimal(raw):.2f}')
        except InvalidOperation:
            continue
    return amounts


def _times(text):
    times = set()
    for hour, minute, half in TIME.findall(text or ''):
        hour = int(hour)
        if 1 <= hour <= 12:
            times.add(f'{hour}:{minute or "00"}{half.lower()}m')
    return times