"""
The obligations ledger (Layer 1, Step 1.3, 11 Nov 2026).

What is still undone for a customer, and whose job it is. Worked out from a
visit's events every time it is asked: a pure function that stores nothing,
so it always agrees with the facts and can never drift from them.

Events OPEN obligations; later events DISCHARGE them:

  files     a customer's file arrived      -> claimed, opened, a job made, or a person took it on
  reply     a customer wrote words          -> anyone answered (staff or Octos)
  payment   a quote or payment link went out -> the payment arrived
  ready     a job reached DONE              -> the ready message went out

Who owns an open obligation: the attendant when the customer is being served
at the counter, the staff member chatting when a person has the conversation,
the system for ready notices, and otherwise Octos. Octos speaks only to
discharge an obligation it owns.
"""
from dataclasses import dataclass, field

from apps.spine import kinds

FILES, REPLY, PAYMENT, READY = 'files', 'reply', 'payment', 'ready'

DISCHARGES = {
    FILES: {kinds.COUNTER_CLAIMED, kinds.FILE_OPENED, kinds.JOB_CREATED, kinds.STAFF_TOOK_OVER},
    PAYMENT: {kinds.PAYMENT_SUCCEEDED, kinds.JOB_PAID, kinds.JOB_DEPOSIT_PAID},
}


@dataclass
class Obligation:
    what: str                 # files, reply, payment, ready
    opened_by: int            # the event that opened it
    owner: str = 'octos'      # octos, attendant, staff, system
    discharged_by: int = None # the event that closed it, if any
    detail: dict = field(default_factory=dict)

    @property
    def open(self):
        return self.discharged_by is None


def ledger(visit, handled_by=None):
    """
    Every obligation in this visit, open and discharged, in order.
    handled_by: the conversation's current handler (OCTOS, STAFF, COUNTER).
    """
    events = list(visit.events.order_by('occurred_at', 'id'))
    counter = handled_by == 'COUNTER' or visit.presence == 'AT_COUNTER'
    person = 'attendant' if counter else ('staff' if handled_by == 'STAFF' else 'octos')

    items = []
    for i, e in enumerate(events):
        later = events[i + 1:]
        if e.kind == kinds.MESSAGE_RECEIVED:
            if e.payload.get('has_file'):
                items.append(_watch(Obligation(FILES, e.pk, owner=person), later, DISCHARGES[FILES]))
            else:
                answered = next((x.pk for x in later if x.kind == kinds.MESSAGE_SENT
                                 and not x.payload.get('system_kind')), None)
                items.append(Obligation(REPLY, e.pk, owner=person, discharged_by=answered))
        elif e.kind in (kinds.QUOTE_GIVEN, kinds.PAYMENT_LINK_SENT):
            items.append(_watch(Obligation(PAYMENT, e.pk, owner='customer'), later, DISCHARGES[PAYMENT]))
        elif e.kind == kinds.JOB_READY:
            told = next((x.pk for x in later if x.kind == kinds.MESSAGE_SENT
                         and x.payload.get('system_kind') == 'ready'), None)
            items.append(Obligation(READY, e.pk, owner='system', discharged_by=told))
    return items


def _watch(obligation, later, discharging_kinds):
    obligation.discharged_by = next((x.pk for x in later if x.kind in discharging_kinds), None)
    return obligation


def files_handled(visit, upto_event_id=None):
    """True when every file in this visit (up to an event) has been handled by someone."""
    files = [o for o in ledger(visit) if o.what == FILES
             and (upto_event_id is None or o.opened_by <= upto_event_id)]
    return bool(files) and all(not o.open for o in files)
