"""
WhatsApp webhook: verification, signature, receiving, robustness and who
gets notified. Nothing here calls Meta; Step 1 never does.
"""
import hashlib
import hmac
import json
from unittest.mock import patch

from django.test import TestCase, override_settings

from apps.accounts.models.role import Role
from apps.communications.models import Conversation, Message, WhatsAppEvent
from apps.communications.tests import make_conversation, make_org, make_user
from apps.customers.models.customer import CustomerProfile
from apps.organization.models import Branch

URL = '/api/v1/communications/webhook/whatsapp/'
SECRET = 'test-app-secret'
TOKEN = 'test-verify-token'
PHONE_ID = '100200300'
AMA = '233244123456'  # as WhatsApp sends it: country code, no '+'


def text(body, wamid='wamid.A1', sender=AMA):
    return {'from': sender, 'id': wamid, 'timestamp': '1762270000',
            'type': 'text', 'text': {'body': body}}


def delivery(*messages, statuses=(), number_id=PHONE_ID, name='Ama'):
    return {
        'object': 'whatsapp_business_account',
        'entry': [{'id': 'WABA', 'changes': [{'field': 'messages', 'value': {
            'messaging_product': 'whatsapp',
            'metadata': {'display_phone_number': '233551969777',
                         'phone_number_id': number_id},
            'contacts': [{'profile': {'name': name}, 'wa_id': AMA}],
            'messages': list(messages),
            'statuses': list(statuses),
        }}]}],
    }


@override_settings(WHATSAPP_APP_SECRET=SECRET, WHATSAPP_VERIFY_TOKEN=TOKEN,
                   WHATSAPP_PHONE_NUMBER_ID=PHONE_ID)
class WebhookTestCase(TestCase):

    def post_raw(self, raw, signature=None):
        if signature is None:
            signature = 'sha256=' + hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
        return self.client.post(URL, data=raw, content_type='application/json',
                                HTTP_X_HUB_SIGNATURE_256=signature)

    def deliver(self, payload):
        """Signed delivery; asserts 200 so a failure says where it failed."""
        res = self.post_raw(json.dumps(payload).encode())
        self.assertEqual(res.status_code, 200, res.content)
        return res

    def conversation(self, phone='+233244123456'):
        return Conversation.objects.get(contact_phone=phone, channel=Conversation.WHATSAPP)


class VerificationTests(WebhookTestCase):

    def test_right_token_echoes_challenge_as_plain_text(self):
        res = self.client.get(URL, {'hub.mode': 'subscribe',
                                    'hub.verify_token': TOKEN, 'hub.challenge': '12345'})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.content, b'12345')  # no JSON quotes
        self.assertTrue(res['Content-Type'].startswith('text/plain'))

    def test_wrong_token_refused(self):
        res = self.client.get(URL, {'hub.mode': 'subscribe',
                                    'hub.verify_token': 'guess', 'hub.challenge': '12345'})
        self.assertEqual(res.status_code, 403)

    @override_settings(WHATSAPP_VERIFY_TOKEN='')
    def test_no_token_configured_refuses_everything(self):
        res = self.client.get(URL, {'hub.mode': 'subscribe',
                                    'hub.verify_token': '', 'hub.challenge': '12345'})
        self.assertEqual(res.status_code, 403)


class SignatureTests(WebhookTestCase):

    def test_missing_signature_refused_and_nothing_stored(self):
        res = self.post_raw(json.dumps(delivery(text('hi'))).encode(), signature='')
        self.assertEqual(res.status_code, 401)
        self.assertEqual(WhatsAppEvent.objects.count(), 0)

    def test_wrong_signature_refused(self):
        res = self.post_raw(json.dumps(delivery(text('hi'))).encode(),
                            signature='sha256=' + '0' * 64)
        self.assertEqual(res.status_code, 401)
        self.assertEqual(Message.objects.count(), 0)

    @override_settings(WHATSAPP_APP_SECRET='')
    def test_no_secret_configured_refuses_everything(self):
        res = self.post_raw(json.dumps(delivery(text('hi'))).encode(), signature='sha256=x')
        self.assertEqual(res.status_code, 401)
        self.assertEqual(WhatsAppEvent.objects.count(), 0)

    def test_valid_signature_stored(self):
        self.deliver(delivery(text('hi')))
        self.assertEqual(WhatsAppEvent.objects.count(), 1)

    def test_unreadable_body_refused_and_not_stored(self):
        res = self.post_raw(b'not json')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(WhatsAppEvent.objects.count(), 0)


class ReceivingTests(WebhookTestCase):

    def test_text_opens_a_company_conversation(self):
        self.deliver(delivery(text('Hi, good evening, please are you around')))

        conv = self.conversation()
        self.assertIsNone(conv.branch)
        self.assertEqual(conv.contact_name, 'Ama')
        msg = conv.messages.get()
        self.assertEqual(msg.direction, Message.INBOUND)
        self.assertEqual(msg.channel, Message.WHATSAPP)
        self.assertEqual(msg.body, 'Hi, good evening, please are you around')
        self.assertEqual(msg.external_id, 'wamid.A1')

        event = WhatsAppEvent.objects.get()
        self.assertIsNotNone(event.processed_at)
        self.assertEqual(event.error, '')

    def test_meta_retry_recorded_once(self):
        self.deliver(delivery(text('hi')))
        self.deliver(delivery(text('hi')))
        self.assertEqual(Message.objects.count(), 1)
        self.assertEqual(WhatsAppEvent.objects.count(), 2)  # both deliveries kept

    def test_one_number_one_conversation(self):
        self.deliver(delivery(text('hi', wamid='wamid.A1')))
        self.deliver(delivery(text('is my job ready?', wamid='wamid.A2')))
        self.assertEqual(Conversation.objects.count(), 1)
        conv = self.conversation()
        self.assertEqual(conv.messages.count(), 2)
        self.assertEqual(conv.unread_count, 2)

    def test_number_from_abroad_parses(self):
        self.deliver(delivery(text('hello', sender='15145828114')))
        self.assertTrue(Conversation.objects.filter(contact_phone='+15145828114').exists())

    def test_image_keeps_media_id_and_caption(self):
        image = {'from': AMA, 'id': 'wamid.IMG', 'timestamp': '1762270000', 'type': 'image',
                 'image': {'id': 'MEDIA123', 'mime_type': 'image/jpeg',
                           'caption': 'print 5 copies of this'}}
        self.deliver(delivery(image))
        msg = Message.objects.get()
        self.assertEqual(msg.message_type, Message.IMAGE)
        self.assertEqual(msg.media_id, 'MEDIA123')
        self.assertEqual(msg.body, 'print 5 copies of this')

    def test_unknown_type_shown_never_dropped(self):
        odd = {'from': AMA, 'id': 'wamid.ODD', 'timestamp': '1762270000', 'type': 'order'}
        self.deliver(delivery(odd))
        msg = Message.objects.get()
        self.assertIn('order', msg.body)

    def test_delivery_for_another_number_ignored(self):
        self.deliver(delivery(text('hi'), number_id='999999'))
        self.assertEqual(Message.objects.count(), 0)
        self.assertEqual(WhatsAppEvent.objects.get().error, '')

    def test_known_customer_linked(self):
        ama = CustomerProfile.objects.create(first_name='Ama', last_name='Mensah',
                                             phone='+233244123456', customer_type='INDIVIDUAL')
        self.deliver(delivery(text('hi')))
        self.assertEqual(self.conversation().customer, ama)

    def test_resolved_thread_reopens(self):
        make_conversation(None, contact_phone='+233244123456', status=Conversation.RESOLVED)
        self.deliver(delivery(text('one more thing')))
        self.assertEqual(self.conversation().status, Conversation.OPEN)
        self.assertEqual(Conversation.objects.count(), 1)

    def test_spam_stays_spam(self):
        make_conversation(None, contact_phone='+233244123456', status=Conversation.SPAM)
        self.deliver(delivery(text('buy followers')))
        self.assertEqual(self.conversation().status, Conversation.SPAM)

    def test_statuses_alone_record_nothing(self):
        status = {'id': 'wamid.OUT1', 'status': 'delivered', 'timestamp': '1762270000',
                  'recipient_id': AMA}
        self.deliver(delivery(statuses=[status]))
        self.assertEqual(Message.objects.count(), 0)
        self.assertEqual(WhatsAppEvent.objects.get().error, '')


class RobustnessTests(WebhookTestCase):

    def test_one_bad_message_does_not_stop_the_others(self):
        broken = {'id': 'wamid.BAD', 'type': 'text', 'text': {'body': 'no sender'}}
        self.deliver(delivery(text('first', wamid='wamid.A1'), broken,
                              text('third', wamid='wamid.A3')))
        self.assertEqual(Message.objects.count(), 2)
        self.assertIn('wamid.BAD', WhatsAppEvent.objects.get().error)

    @override_settings(WHATSAPP_PHONE_NUMBER_ID='')
    def test_missing_number_setting_kept_and_recorded(self):
        self.deliver(delivery(text('hi')))  # still 200: Meta must not retry into it
        event = WhatsAppEvent.objects.get()
        self.assertIn('WHATSAPP_PHONE_NUMBER_ID', event.error)
        self.assertEqual(Message.objects.count(), 0)


class NotificationTests(WebhookTestCase):

    def setUp(self):
        role, _ = Role.objects.get_or_create(
            name='BRANCH_MANAGER', defaults={'display_name': 'Branch Manager'})
        self.branch = make_org()
        closed = Branch.objects.create(name='Closed', code='CLS',
                                       region=self.branch.region, is_active=False)

        self.manager = make_user('manager@test.com', self.branch)
        self.manager.role = role
        self.manager.save()

        closed_manager = make_user('closed@test.com', closed)
        closed_manager.role = role
        closed_manager.save()

        self.staff = make_user('staff@test.com', self.branch)  # no role

    def test_company_conversation_notifies_active_branch_managers_only(self):
        with patch('apps.notifications.signals.notify_many') as notify_many:
            self.deliver(delivery(text('is my job ready?')))
        self.assertTrue(notify_many.called, 'nobody was notified')
        self.assertEqual(notify_many.call_args.kwargs['recipients'], [self.manager])

    def test_assigned_conversation_goes_to_assignee(self):
        from apps.notifications.signals import _conversation_assignees
        conv = make_conversation(None, contact_phone='+233200000001', assigned_to=self.staff)
        self.assertEqual(_conversation_assignees(conv), [self.staff])

    def test_branch_conversation_unchanged(self):
        from apps.notifications.signals import _conversation_assignees
        conv = make_conversation(self.branch, contact_phone='+233200000002')
        self.assertEqual(_conversation_assignees(conv), [self.manager])