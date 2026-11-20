"""
Did the team already deal with it? (20 Nov 2026)

Before Octos speaks into a chat it picked up (taken back from a person who
never wrote, or a remote customer gone quiet after a file), it looks for
proof, not from the customer, that the team already acted: a person wrote
or sent a file back, a job was made, a receipt went out, an order was paid.
If there is, it stays quiet. Khofi: a "just checking in" after the work was
done makes Octos sound like he isn't part of the team and doesn't know
what's going on.

Opening a file is not proof: Noel's photo was opened and nobody wrote back.
"""
from django.db.models import Q


def team_dealt_with(conversation, since):
    """What the team did after `since`, in a few words, or '' when nothing shows it."""
    from apps.communications.models import Message
    from apps.jobs.models import Job
    from apps.spine import kinds
    from apps.spine.models import Event
    from apps.storefront.models import OnlineOrder

    person = (conversation.messages.filter(direction=Message.OUTBOUND, is_internal_note=False,
                                           sent_by__isnull=False, created_at__gt=since)
              .select_related('sent_by').order_by('created_at').first())
    if person is not None:
        who = person.sent_by.first_name or 'A teammate'
        return f'{who} sent them a file' if person.media_file or person.media_id else f'{who} replied'
    jobs = Q(conversations=conversation)
    if conversation.customer_id:
        jobs |= Q(customer_id=conversation.customer_id)
    job = (Job.objects.filter(jobs, created_at__gt=since).exclude(status__in=[Job.CANCELLED, Job.VOIDED])
           .order_by('created_at').first())
    if job is not None:
        return f'job {job.job_number} was made'
    if Event.objects.filter(conversation=conversation, occurred_at__gt=since,
                            kind__in=[kinds.JOB_CREATED, kinds.JOB_LINKED, kinds.STAFF_HANDED_BACK]).exists():
        return 'the team recorded the job'
    if conversation.messages.filter(kind='receipt', created_at__gt=since).exists():
        return 'their receipt was sent'
    paid = (OnlineOrder.objects.filter(notes__contains=f'(conversation {conversation.pk})', paid_at__gt=since)
            .order_by('paid_at').first())
    if paid is not None:
        return f'they paid for {paid.order_number}'
    return ''
