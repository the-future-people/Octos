"""
record(): the one front door to the spine.

Every part of Octos writes events through this function, so the rules
(known kinds only, one event per idempotency key, every new event joined to
its visit) live in one place.

Use it inside the same transaction as the change it describes:

    with transaction.atomic():
        conversation.handled_by = Conversation.STAFF
        conversation.save(update_fields=['handled_by'])
        record(kinds.STAFF_TOOK_OVER, actor=Event.STAFF, actor_user=user,
               conversation=conversation, reason='took over from the inbox')

Then the change and its event are saved together or not at all.
"""
from django.db import transaction

from apps.spine import kinds
from apps.spine.models import Event


class UnknownEventKind(ValueError):
    """record() was given a kind that isn't in apps/spine/kinds.py."""


def record(kind, *, actor=Event.SYSTEM, actor_user=None, customer=None, conversation=None,
           job=None, branch=None, payload=None, reason='', key=None, occurred_at=None,
           _visit=None):
    """
    Write one event. Returns (event, created).

    key: the idempotency key. Give one whenever the fact has a natural unique
    id: 'wa:<wamid>' for a WhatsApp message, 'paystack:<reference>' for a
    payment. If an event with that key exists, nothing new is written and
    created is False, so a re-delivered webhook is harmless.

    _visit: internal, for visits.close() recording its own closing event.
    """
    if kind not in kinds.ALL:
        raise UnknownEventKind(f'{kind!r} is not in apps/spine/kinds.py')

    fields = {
        'kind': kind,
        'actor': actor,
        'actor_user': actor_user,
        'customer': customer,
        'conversation': conversation,
        'job': job,
        'branch': branch,
        'payload': payload or {},
        'reason': reason,
    }
    if occurred_at is not None:
        fields['occurred_at'] = occurred_at
    if _visit is not None:
        fields['visit'] = _visit

    with transaction.atomic():
        if key:
            # get_or_create relies on the unique constraint: if two workers race
            # with the same key, the database lets exactly one insert succeed and
            # the other gets the existing row back.
            event, created = Event.objects.get_or_create(idempotency_key=key, defaults=fields)
        else:
            event, created = Event.objects.create(**fields), True

        # A new fact joins its visit. A repeat changes nothing, visits included.
        if created and _visit is None:
            from apps.spine.visits import attach
            attach(event)

    return event, created
