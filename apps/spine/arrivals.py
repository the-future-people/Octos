"""
Files arriving now (Layer 2, Step 2.3, 11 Nov 2026).

Which customers have sent files that nobody has picked up yet? The attendant's
Claim strip shows them, one row each, so the person in front of the counter can
be matched to their files with one tap.

A plain function, not an API view: the view is a thin wrapper, so the same
answer can later feed a desktop notification or the BM's overview.

A visit appears while its files obligation is open (apps/spine/obligations.py)
and disappears by itself once someone claims it, opens the files, takes it on
or makes the job.
"""
from datetime import timedelta

from django.utils import timezone

from apps.spine.obligations import FILES, ledger

WITHIN = timedelta(hours=1)


def _name(conversation):
    customer = conversation.customer
    for field in ('full_name', 'name', 'first_name'):
        value = (getattr(customer, field, '') or '').strip() if customer else ''
        if value:
            return value
    return (conversation.contact_name or conversation.contact_username or 'Customer').strip()


def _tail(conversation):
    digits = ''.join(c for c in (conversation.contact_phone or '') if c.isdigit())
    return digits[-3:] if digits else ''


def arrivals(now=None, branch=None):
    """
    One row per customer with files waiting, oldest first. Each row:
    conversation, name, number tail, files (Message objects), since, and the
    presence belief for the latest file.
    """
    from apps.communications.assistant import counter
    from apps.communications.models import Message
    from apps.spine import presence
    from apps.spine.models import Event, Visit

    now = now or timezone.now()
    visits = (Visit.objects.filter(closed_at__isnull=True, last_activity_at__gte=now - WITHIN)
              .select_related('conversation', 'conversation__customer', 'branch'))
    if branch is not None:
        from django.db.models import Q
        visits = visits.filter(Q(branch=branch) | Q(branch__isnull=True))

    opened = counter.shop_open(now)
    rows = []
    for visit in visits:
        waiting = [o for o in ledger(visit) if o.what == FILES and o.open]
        if not waiting or visit.conversation is None:
            continue
        events = Event.objects.filter(pk__in=[o.opened_by for o in waiting])
        ids = [e.payload.get('message_id') for e in events if e.payload.get('message_id')]
        files = list(Message.objects.filter(pk__in=ids).order_by('created_at'))
        if not files:
            continue
        belief = presence.for_message(visit.conversation, files[-1], now, opened)
        rows.append({
            'conversation': visit.conversation,
            'name': _name(visit.conversation),
            'number_tail': _tail(visit.conversation),
            'files': files,
            'since': files[0].created_at,
            'presence': belief.band,
            'p': round(belief.p, 2),
        })
    rows.sort(key=lambda r: r['since'])
    return rows
