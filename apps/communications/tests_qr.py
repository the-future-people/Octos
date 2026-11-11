"""
The counter QR's invisible signature (Layer 2, Step 2.1).
"""
from unittest.mock import patch
from urllib.parse import unquote

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.communications.assistant import counter, qr
from apps.communications.models import Conversation, Message
from apps.communications.services.whatsapp_inbound import _receive
from apps.communications.tests import make_org
from apps.spine import kinds
from apps.spine.models import Event, Visit


class SignatureTests(TestCase):
    def test_a_signature_round_trips(self):
        self.assertEqual(qr.decode(qr.GREETING + qr.encode(7)), (7, True))

    def test_the_signature_is_invisible(self):
        text = qr.GREETING + qr.encode(7)
        self.assertEqual(qr.clean(text), qr.GREETING)
        self.assertTrue(qr.has_invisible(text))

    def _flip_last(self, sig):
        last = ord(sig[-1]) - qr.BASE
        return sig[:-1] + chr(qr.BASE + (last ^ 1))

    def test_a_tampered_signature_fails(self):
        branch, ok = qr.decode(qr.GREETING + self._flip_last(qr.encode(7)))
        self.assertEqual(branch, 7)
        self.assertFalse(ok)

    def test_one_branchs_signature_does_not_prove_another(self):
        # Branch 8's number with branch 7's signature
        forged = qr.encode(8)[:4] + qr.encode(7)[4:]
        branch, ok = qr.decode(forged)
        self.assertEqual(branch, 8)
        self.assertFalse(ok)

    def test_the_signature_is_ten_characters(self):
        self.assertEqual(len(qr.encode(7)), 10)

    def test_plain_text_has_no_signature(self):
        self.assertEqual(qr.decode('Hi Farhat 👋'), (None, False))

    def test_the_link_carries_greeting_and_signature(self):
        url = qr.link(7, '+233 55 196 9777')
        self.assertTrue(url.startswith('https://wa.me/233551969777?text='))
        self.assertEqual(qr.decode(unquote(url.split('text=')[1])), (7, True))


@override_settings(OCTOS_ASSISTANT_MODE='off')
@patch('apps.communications.services.whatsapp_inbound._keep_media')
@patch('apps.communications.assistant.counter.shop_open', return_value=True)
class ArrivalTests(TestCase):
    def setUp(self):
        self.branch = make_org()
        self.branch.is_trading = True
        self.branch.save()

    def _send(self, body, wamid='wamid.QR1'):
        _receive({'id': wamid, 'from': '233244123456', 'type': 'text', 'text': {'body': body}}, 'Ama')
        return Message.objects.get(external_id=wamid)

    def test_a_signed_greeting_is_a_verified_counter_presence(self, _open, _media):
        message = self._send(qr.GREETING + qr.encode(self.branch.pk))
        event = Event.objects.get(kind=kinds.PRESENCE_COUNTER)
        self.assertTrue(event.payload['verified'])
        self.assertEqual(event.branch, self.branch)
        self.assertEqual(Visit.objects.get().presence, Visit.AT_COUNTER)
        self.assertTrue(counter.in_visit(Conversation.objects.get()))
        self.assertEqual(message.body, qr.GREETING)          # stored as people read it

    def test_a_plain_greeting_is_not_proof(self, _open, _media):
        self._send('Hi Farhat 👋')
        self.assertFalse(Event.objects.filter(kind=kinds.PRESENCE_COUNTER).exists())
        self.assertFalse(counter.in_visit(Conversation.objects.get()))

    def test_a_forged_signature_is_recorded_but_proves_nothing(self, _open, _media):
        sig = qr.encode(self.branch.pk)
        broken = sig[:-1] + chr(qr.BASE + ((ord(sig[-1]) - qr.BASE) ^ 1))
        self._send(qr.GREETING + broken)
        self.assertFalse(counter.in_visit(Conversation.objects.get()))
        self.assertFalse(Event.objects.filter(kind=kinds.PRESENCE_COUNTER, payload__verified=True).exists())

    def test_octos_acknowledges_a_verified_qr_naming_the_branch(self, _open, _media):
        message = self._send(qr.GREETING + qr.encode(self.branch.pk))
        said, why = counter.step(Conversation.objects.get(), message, timezone.now())
        self.assertIn('will take it from here', said)
        self.assertEqual(why, 'counter visit started')
