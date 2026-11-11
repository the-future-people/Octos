"""
Files opened, no job recorded (Layer 2, Step 2.4b, 11 Nov 2026).

For the BM before closing the day: every chat where a person opened a
customer's file that day, and no job was ever made or linked for that chat.
A customer who changed their mind leaves the same trace as work done and not
recorded, so this is a list to look at, never a gate: the BM decides.
"""
from django.utils import timezone


def unrecorded_files(branch=None, day=None):
    from apps.spine import kinds
    from apps.spine.arrivals import _name, _tail
    from apps.spine.models import Event

    day = day or timezone.localdate()
    opened = (Event.objects
              .filter(kind=kinds.FILE_OPENED, occurred_at__date=day, visit__isnull=False)
              .select_related('visit', 'visit__conversation', 'actor_user')
              .order_by('occurred_at'))

    by_visit = {}
    for event in opened:
        by_visit.setdefault(event.visit_id, []).append(event)

    rows = []
    for events in by_visit.values():
        visit = events[0].visit
        conversation = visit.conversation
        if branch is not None and visit.branch_id and visit.branch_id != branch.pk:
            continue
        if visit.events.filter(kind__in=[kinds.JOB_CREATED, kinds.JOB_LINKED]).exists():
            continue
        if conversation is not None and conversation.jobs.filter(created_at__date=day).exists():
            continue
        who = []
        for e in events:
            name = getattr(e.actor_user, 'full_name', '') or 'Staff'
            if name not in who:
                who.append(name)
        rows.append({
            'conversation_id': conversation.pk if conversation else None,
            'name': _name(conversation) if conversation else 'Customer',
            'number_tail': _tail(conversation) if conversation else '',
            'opened_by': who,
            'first_opened_at': events[0].occurred_at,
            'files_opened': len(events),
            'visit_outcome': visit.outcome or 'open',
        })
    return rows
