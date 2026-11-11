"""
The replay harness (Layer 1, Step 1.4, 11 Nov 2026).

Drives the real pipeline through a scenario taken from real conversations:
customer messages arrive through the same _receive() as Meta's webhook,
Octos takes its turns through the same brain.respond(), staff tap the same
buttons, and a fake clock moves time forward by hand so a two-hour gap takes
no time at all. Only the AI model is a stand-in (it always says MODEL_REPLY),
so what is tested is Octos's judgement about whether to speak, not its words.

    with Replay(shop_open=True) as r:
        qr = r.customer("Hi, I'm at the Westland counter")
        r.wait(seconds=5)
        photo = r.customer(file=True)
        r.wait(seconds=8);  r.octos_turn(qr)      # skipped: a newer message
        r.wait(minutes=2);  r.octos_turn(photo)
        assert r.said() == []
"""
from contextlib import ExitStack
from datetime import timedelta
from unittest.mock import patch

from django.utils import timezone

from apps.communications.models import Conversation, Message
from apps.spine import kinds
from apps.spine.models import Event, Visit
from apps.spine.recorder import record

PHONE = '233244000100'          # an invented number: replays never use a real customer's
MODEL_REPLY = 'MODEL_REPLY'


class Clock:
    """Stands in for timezone.now(), and only moves when told to."""

    def __init__(self, start):
        self.now = start

    def __call__(self):
        return self.now


class Replay:
    def __init__(self, shop_open=True, start=None):
        self.clock = Clock(start or timezone.now().replace(hour=9, minute=0, second=0, microsecond=0))
        self.shop_open = shop_open
        self.counter = 0
        self.stack = ExitStack()

    # ── Setting the stage ────────────────────────────────────
    def __enter__(self):
        s = self.stack
        s.enter_context(patch('django.utils.timezone.now', self.clock))
        # Event's default captured the original timezone.now when the model was
        # defined, so the clock must be fitted there too.
        s.enter_context(patch.object(Event._meta.get_field('occurred_at'), '_get_default', self.clock))
        s.enter_context(patch('apps.communications.assistant.counter.shop_open', return_value=self.shop_open))
        s.enter_context(patch('apps.communications.services.whatsapp_inbound._keep_media'))
        s.enter_context(patch('apps.communications.services.whatsapp_client.show_typing', return_value=True))
        s.enter_context(patch('apps.notifications.services.notify_many'))
        from apps.communications.assistant import brain
        s.enter_context(patch.object(brain.time, 'sleep'))   # no 5-second "typing" pauses
        return self

    def __exit__(self, *exc):
        self.stack.close()

    # ── Time ─────────────────────────────────────────────────
    def wait(self, seconds=0, minutes=0, hours=0):
        self.clock.now += timedelta(seconds=seconds, minutes=minutes, hours=hours)

    # ── The customer ─────────────────────────────────────────
    def customer(self, body='', file=False, name='Customer'):
        """A message arriving from Meta, exactly as the webhook hands it on."""
        from apps.communications.services.whatsapp_inbound import _receive
        self.counter += 1
        wamid = f'wamid.REPLAY{self.counter}'
        if file:
            payload = {'id': wamid, 'from': PHONE, 'type': 'image',
                       'image': {'id': f'media-{self.counter}', 'mime_type': 'image/jpeg'}}
        else:
            payload = {'id': wamid, 'from': PHONE, 'type': 'text', 'text': {'body': body}}
        _receive(payload, name)
        return Message.objects.get(external_id=wamid)

    # ── Octos ────────────────────────────────────────────────
    def octos_turn(self, trigger):
        """The run the worker would make for this message once its wait is over."""
        from apps.communications.assistant import brain
        from apps.communications.tests_assistant_brain import Model, says, text
        with patch('anthropic.Anthropic', return_value=Model(says(text(MODEL_REPLY)))):
            return brain.respond(self.conversation.pk, trigger.pk)

    # ── Staff ────────────────────────────────────────────────
    def at_counter_tap(self):
        """The attendant's 'At the counter' button."""
        from apps.communications.assistant import counter
        counter.start_visit(self.conversation)
        record(kinds.COUNTER_CLAIMED, actor=Event.STAFF, conversation=self.conversation,
               reason='Marked at the counter (replay).')

    def take_over(self, user):
        from apps.communications.services import handover
        handover.take_over(self.conversation, user)

    def job_created(self):
        """The attendant records the job (the Layer 2 link will make this automatic)."""
        record(kinds.JOB_CREATED, actor=Event.STAFF, conversation=self.conversation,
               reason='Job recorded at the counter (replay).')

    def payment_link_sent(self):
        record(kinds.PAYMENT_LINK_SENT, actor=Event.OCTOS, conversation=self.conversation)

    def handover_watch(self):
        from apps.communications.services import handover
        return handover.watch(now=self.clock.now)

    def sweep(self):
        from apps.spine.visits import close_quiet
        return close_quiet(now=self.clock.now)

    # ── What happened ────────────────────────────────────────
    @property
    def conversation(self):
        return Conversation.objects.get(contact_phone='+' + PHONE)

    def said(self):
        """Every message the customer actually received, in order."""
        return list(self.conversation.messages
                    .filter(direction=Message.OUTBOUND, is_internal_note=False)
                    .order_by('created_at', 'id').values_list('body', flat=True))

    def visits(self):
        return list(Visit.objects.filter(conversation=self.conversation).order_by('opened_at'))
