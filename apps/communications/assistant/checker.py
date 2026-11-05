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

MONEY = re.compile(
    r'(?:GHS|GH₵|GHC|₵)\s*([\d,]+(?:\.\d{1,2})?)'
    r'|([\d,]+(?:\.\d{1,2})?)\s*(?:cedis?|ghs)\b',
    re.IGNORECASE,
)
TIME = re.compile(r'\b(\d{1,2})(?::(\d{2}))?\s*([ap])\.?\s?m\b\.?', re.IGNORECASE)
REF = re.compile(r'\bref(?:erence)?\.?\s*(?:no\.?\s*)?#?\s*(\d{2,})\b', re.IGNORECASE)


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