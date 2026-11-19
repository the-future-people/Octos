"""
Octos acting for the owner on a customer chat (19 Nov 2026).

The owner read a "customer waiting" alert and told his line: "Respond to
the message and see what he wants. Report back." Then: "Check back in a
bit." Octos could only look. Now, on his word, it can:

  answer_now     take the chat back from staff and let Octos answer the
                 customer at once, as it does when a reminder is ignored
  watch          report to the owner when the customer writes again: what
                 they said and how it was answered
  check_later    come back in N minutes, look, and report

Octos still never writes to a customer in the owner's words, and changes no
job: the customer's answer comes from the customer assistant, under all of
its own rules.
"""
import logging
import re
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.communications.models import Conversation, Message, OwnerWatch

logger = logging.getLogger(__name__)

WATCH_HOURS = 12
REPORT_AFTER = 150          # seconds after the customer's message: Octos has answered by then
MAX_REPORTS = 10
CHECK_MIN, CHECK_MAX = 2, 360


def answer_now(conversation):
    """
    Octos takes the chat and answers the customer now. Returns what happened,
    for the owner: {'answered': bool, 'was_with': name or None, 'say': ...}.
    """
    from apps.communications.services import handover
    from apps.communications.services.whatsapp_inbound import wake_octos
    was_with = None
    if conversation.handled_by == Conversation.STAFF:
        was_with = conversation.assigned_to.full_name if conversation.assigned_to_id else 'a person'
    waiting = handover.waiting_since(conversation) is not None
    if conversation.handled_by == Conversation.STAFF:
        # Taking back, as after an ignored reminder: Octos answers what's waiting.
        handover.hand_back(conversation, why='the owner asked Octos to answer.')
    elif waiting:
        last = (conversation.messages.filter(is_internal_note=False, direction=Message.INBOUND)
                .exclude(kind__in=Message.QUIET_KINDS).order_by('-created_at').first())
        if last is not None:
            wake_octos(conversation, last)
    result = {'answered': waiting, 'was_with': was_with}
    if not waiting:
        result['say'] = ('The customer is not waiting: the last word in the chat is ours. Octos has the chat '
                         'now and will answer their next message.' if was_with else
                         'The customer is not waiting: the last word in the chat is ours.')
    return result


def watch(conversation, mode=OwnerWatch.NEXT):
    """Report the customer's next reply (or every reply) to the owner. One watch per chat."""
    now = timezone.now()
    last = conversation.messages.filter(is_internal_note=False).order_by('-created_at', '-pk').first()
    with transaction.atomic():
        OwnerWatch.objects.filter(conversation=conversation, done_at__isnull=True).update(done_at=now)
        w = OwnerWatch.objects.create(conversation=conversation, mode=mode,
                                      ends_at=now + timedelta(hours=WATCH_HOURS), reported_up_to=last)
    return w


def stop(conversation):
    return OwnerWatch.objects.filter(conversation=conversation, done_at__isnull=True).update(done_at=timezone.now())


def customer_wrote(conversation, message):
    """
    From the webhook: a watched chat's customer wrote. The report waits a
    little, so it can say how Octos (or a person) answered; each new message
    starts the wait again and only the latest one reports.
    """
    if not OwnerWatch.objects.filter(conversation=conversation, done_at__isnull=True,
                                     ends_at__gt=timezone.now()).exists():
        return
    from apps.communications.tasks import report_watched_chat
    transaction.on_commit(lambda: report_watched_chat.apply_async((conversation.pk, message.pk),
                                                                  countdown=REPORT_AFTER))


def report(conversation_id, trigger_id):
    """The report itself: what the customer said since the last one, and the answer."""
    from apps.communications.services import owner_line
    now = timezone.now()
    w = (OwnerWatch.objects.filter(conversation_id=conversation_id, done_at__isnull=True, ends_at__gt=now)
         .select_related('conversation', 'reported_up_to').first())
    if w is None:
        return None
    conversation = w.conversation
    newer = (conversation.messages.filter(direction=Message.INBOUND, is_internal_note=False, pk__gt=trigger_id)
             .exclude(kind__in=Message.QUIET_KINDS).exists())
    if newer:
        return None                       # a later message reports instead
    since = conversation.messages.filter(is_internal_note=False).exclude(kind__in=Message.QUIET_KINDS)
    if w.reported_up_to_id:
        since = since.filter(created_at__gt=w.reported_up_to.created_at)
    rows = list(since.select_related('sent_by').order_by('created_at', 'pk'))
    theirs = [m for m in rows if m.direction == Message.INBOUND]
    if not theirs:
        return None
    body = _report_body(conversation, rows)
    sent = owner_line.tell('ANSWER', body, ref=f'chat:{conversation.pk}',
                           knock=f'{conversation.display_name} replied on WhatsApp.')
    w.reported_up_to = rows[-1]
    w.reports += 1
    if w.mode == OwnerWatch.NEXT or w.reports >= MAX_REPORTS:
        w.done_at = now
    w.save(update_fields=['reported_up_to', 'reports', 'done_at'])
    return sent


def _report_body(conversation, rows):
    name = conversation.display_name
    lines = [f'👀 *{name} replied*']
    last_in = max(i for i, m in enumerate(rows) if m.direction == Message.INBOUND)
    files = 0
    said = []
    for m in rows[:last_in + 1]:
        if m.direction != Message.INBOUND:
            continue
        if m.message_type in (Message.IMAGE, Message.VIDEO, Message.DOCUMENT, Message.AUDIO):
            files += 1
        if m.body:
            said.append(_clip(m.body))
    said = said[-3:]
    if files:
        said.append(f'📎 {files} file{"s" if files > 1 else ""}')
    lines += [f'> {s}' for s in said]
    answers = [m for m in rows[last_in + 1:] if m.direction == Message.OUTBOUND]
    lines.append('')
    if answers:
        last = answers[-1]
        who = last.sent_by.first_name if last.sent_by_id else 'Octos'
        text = _clip(last.body) if last.body else ('a picture' if last.message_type == Message.IMAGE else 'a file')
        lines += [f'_{who} answered:_', f'> {text}']
    elif conversation.handled_by == Conversation.STAFF:
        who = conversation.assigned_to.first_name if conversation.assigned_to_id else 'A person'
        lines.append(f'_{who} has the chat and hasn\'t answered yet._')
    else:
        lines.append('_Not answered yet._')
    return '\n'.join(lines)


def _clip(text, limit=200):
    text = re.sub(r'\s+', ' ', text).strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'


def check_later(minutes, what):
    """Come back in N minutes (2 to 360), look, and report. Returns the minutes used."""
    from apps.communications.tasks import owner_check_later
    minutes = max(CHECK_MIN, min(15 if minutes is None else int(minutes), CHECK_MAX))
    set_at = timezone.now().isoformat()
    owner_check_later.apply_async((what[:300], set_at), countdown=minutes * 60)
    return minutes
