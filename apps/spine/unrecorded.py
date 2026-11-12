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


# ── Jobs recorded after closing time (12 Nov 2026) ─────────────────────────

OTHER_SOURCES = {'USB', 'HARDCOPY', 'EMAIL', 'TYPING'}


def mismatch(sources, from_chat):
    """A WhatsApp chat's job whose items say the files came another way."""
    return bool(from_chat) and bool(set(sources) & OTHER_SOURCES)


def after_hours_jobs(branch, day=None):
    """
    Every job at this branch recorded after today's closing time, with when,
    by whom, for whom, and where its files came from. The hours after closing
    are when work most often goes unrecorded or mis-recorded, so the BM sees
    them with their times before closing the day. Never a gate.
    """
    from datetime import datetime
    from apps.communications.models import Conversation
    from apps.communications.services.chat_customer import chat_identity
    from apps.jobs.models import Job, JobLineItem
    from apps.organization.services import shop_state

    day = day or timezone.localdate()
    noon = timezone.make_aware(datetime.combine(day, datetime.min.time())).replace(hour=12)
    closing = shop_state.closing_time(branch, noon)
    if closing is None:
        return []

    rows = []
    for job in (Job.objects.filter(branch=branch, created_at__gte=closing, created_at__date=day)
                .select_related('customer', 'intake_by').order_by('created_at')):
        sources = list(JobLineItem.objects.filter(job=job).values_list('file_source', flat=True))
        chat = Conversation.objects.filter(jobs=job).first()
        if job.customer_id:
            for_whom = job.customer.display_name or 'Customer'
        else:
            who = chat_identity(job)
            for_whom = who[0] if who else 'Walk-in'
        taker = getattr(job, 'intake_by', None)
        rows.append({
            'job_number': job.job_number,
            'recorded_at': job.created_at,
            'recorded_by': getattr(taker, 'full_name', '') or '—',
            'for': for_whom,
            'conversation_id': chat.pk if chat else None,
            'sources': sorted(set(sources)),
            'mismatch': mismatch(sources, chat is not None),
        })
    return rows
