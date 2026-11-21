"""
Receipts and statements outside the 24-hour window (21 Nov 2026): the
approved messages receipt_ready and account_statement, with the receipt
picture or the statement PDF on top, the way Uber and Bolt reach you.
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings

from apps.communications.models import Conversation, Message
from apps.communications.services import templates, whatsapp_client
from apps.communications.tests import make_conversation
from apps.communications.tests_whatsapp_outbound import customer_wrote
from apps.finance.models import Receipt
from apps.finance.receipt_engine import NOT_APPROVED, ReceiptEngine
from apps.finance.tests import RecoveryFixtureMixin

SEND = 'apps.communications.services.whatsapp_client._send'
UPLOAD = 'apps.communications.services.whatsapp_client.upload_media'
PNG = b'\x89PNG\r\n\x1a\nfake'


class TemplatePayloadTests(SimpleTestCase):

    def test_a_picture_goes_in_the_header_and_the_blanks_in_the_body(self):
        with patch(UPLOAD, return_value='media-1') as upload, patch(SEND, return_value='wamid.1') as send:
            whatsapp_client.send_template('+233244123456', 'receipt_ready', params=['Ama', 'GHS 45.00'],
                                          header=('image', PNG, 'RCP-1.png', 'image/png'))
        upload.assert_called_once_with(PNG, 'RCP-1.png', 'image/png')
        template = send.call_args.args[1]['template']
        self.assertEqual(template['components'][0],
                         {'type': 'header', 'parameters': [{'type': 'image', 'image': {'id': 'media-1'}}]})
        self.assertEqual([p['text'] for p in template['components'][1]['parameters']], ['Ama', 'GHS 45.00'])

    def test_a_document_keeps_its_file_name(self):
        with patch(UPLOAD, return_value='media-2'), patch(SEND, return_value='wamid.2') as send:
            whatsapp_client.send_template('+233244123456', 'account_statement', params=['Ama', 'GHS 340.00'],
                                          header=('document', b'%PDF', 'Statement.pdf', 'application/pdf'))
        header = send.call_args.args[1]['template']['components'][0]['parameters'][0]
        self.assertEqual(header, {'type': 'document', 'document': {'id': 'media-2', 'filename': 'Statement.pdf'}})

    def test_the_wording_and_no_empty_blank(self):
        self.assertEqual(templates.fill(templates.MEDIA_TEMPLATES['receipt_ready']['text'],
                                        ['Ama', 'GHS 45.00']),
                         'Hello Ama, here is your receipt from Farhat Printing Press for GHS 45.00. '
                         'Thank you for choosing Farhat 🙏')
        self.assertEqual(templates.hello_name(''), 'there')


class ReceiptTemplateTests(RecoveryFixtureMixin, TestCase):

    def setUp(self):
        self.receipt = self.add_cash_receipt(self.make_sheet(days_ago=0), 58.50)
        Receipt.objects.filter(pk=self.receipt.pk).update(customer_phone='0244123456', customer_name='Ama Mensah')
        self.receipt.refresh_from_db()
        self.engine = ReceiptEngine(self.branch)
        drawn = patch('apps.finance.services.receipt_image.render', return_value=PNG)
        data = patch('apps.finance.services.receipt_image.receipt_data', return_value={'first_name': 'Ama'})
        fmt = patch('apps.finance.receipt_engine.ReceiptEngine._format_whatsapp_message', return_value='Receipt text')
        for p in (drawn, data, fmt):
            p.start()
            self.addCleanup(p.stop)

    def test_a_customer_who_never_wrote_gets_the_approved_receipt(self):
        with patch(UPLOAD, return_value='media-1'), patch(SEND, return_value='wamid.r1') as send:
            sent, reason = self.engine.send_whatsapp(self.receipt)
        self.assertEqual((sent, reason), (True, ''))
        self.assertEqual(send.call_args.args[1]['template']['name'], 'receipt_ready')
        chat = Conversation.objects.get(contact_phone='+233244123456')
        message = chat.messages.get(kind='receipt')
        self.assertEqual((message.status, message.message_type, message.external_id),
                         (Message.SENT, Message.IMAGE, 'wamid.r1'))
        self.assertIn('Hello Ama, here is your receipt', message.body)
        self.assertIn('GHS 58.50', message.body)
        self.receipt.refresh_from_db()
        self.assertEqual(self.receipt.whatsapp_status, Receipt.DeliveryStatus.SENT)

    def test_inside_the_window_it_goes_as_before(self):
        conv = make_conversation(None, contact_phone='+233244123456')
        customer_wrote(conv, timedelta(minutes=10))
        with patch(SEND) as send, self.captureOnCommitCallbacks(execute=False):
            sent, _ = self.engine.send_whatsapp(self.receipt)
        self.assertTrue(sent)
        send.assert_not_called()                                         # queued as a picture, no template
        self.assertEqual(conv.messages.get(kind='receipt').status, Message.QUEUED)

    def test_not_approved_yet_is_said_plainly(self):
        with patch(UPLOAD, return_value='media-1'), \
                patch(SEND, side_effect=whatsapp_client.WhatsAppError('132001', 'Template does not exist')):
            sent, reason = self.engine.send_whatsapp(self.receipt)
        self.assertEqual((sent, reason), (False, NOT_APPROVED))
        self.receipt.refresh_from_db()
        self.assertNotEqual(self.receipt.whatsapp_status, Receipt.DeliveryStatus.SENT)


class StatementTemplateTests(TestCase):

    def setUp(self):
        from apps.customers.models import CustomerProfile
        from apps.communications.tests import make_org
        self.branch = make_org('-ST')
        self.customer = CustomerProfile.objects.create(first_name='Kwabena', last_name='Dwumfour',
                                                       phone='0555000777', customer_type='INDIVIDUAL')
        self.owes = patch('apps.finance.services.owing.statement', return_value={
            'customer': self.customer, 'owed': [], 'current': [], 'owed_total': Decimal('300'),
            'current_total': Decimal('0'), 'total': Decimal('300')})
        self.owes.start()
        self.addCleanup(self.owes.stop)

    def test_outside_the_window_the_approved_statement_goes_with_the_pdf(self):
        from apps.finance.services.statement_pdf import send_statement
        with patch(UPLOAD, return_value='media-s'), patch(SEND, return_value='wamid.s1') as send:
            sent, why = send_statement(self.customer, self.branch)
        self.assertTrue(sent, why)
        template = send.call_args.args[1]['template']
        self.assertEqual(template['name'], 'account_statement')
        self.assertEqual([p['text'] for p in template['components'][1]['parameters']], ['Kwabena', 'GHS 300.00'])
        message = Message.objects.get(kind='statement')
        self.assertEqual(message.message_type, Message.DOCUMENT)
        self.assertIn('Total due: GHS 300.00', message.body)


@override_settings(WHATSAPP_ACCESS_TOKEN='t', WHATSAPP_PHONE_NUMBER_ID='n')
class UsernameTests(TestCase):
    """
    A customer who writes from a WhatsApp username has no number, only their
    WhatsApp user id (GH.…). Templates reach them by that id, as Meta allows
    since July 2026: the receipt through the job's chat, the statement
    through their chat.
    """

    def setUp(self):
        from apps.customers.models import CustomerProfile
        from apps.communications.tests import make_org
        self.branch = make_org('-UN')
        self.customer = CustomerProfile.objects.create(first_name='Esi', phone='', customer_type='INDIVIDUAL')
        self.chat = make_conversation(None, contact_phone='', contact_user_id='GH.1114480144784115',
                                      contact_name='esi.prints', customer=self.customer)

    def test_the_statement_goes_to_their_user_id(self):
        from apps.finance.services.statement_pdf import send_statement
        owes = {'customer': self.customer, 'owed': [], 'current': [], 'owed_total': Decimal('80'),
                'current_total': Decimal('0'), 'total': Decimal('80')}
        with patch('apps.finance.services.owing.statement', return_value=owes), \
                patch(UPLOAD, return_value='media-u'), \
                patch('apps.communications.services.whatsapp_client.requests.post') as post:
            post.return_value.json.return_value = {'messages': [{'id': 'wamid.u1'}]}
            post.return_value.status_code = 200
            sent, why = send_statement(self.customer, self.branch)
        self.assertTrue(sent, why)
        payload = post.call_args.kwargs['json']
        self.assertEqual(payload['recipient'], 'GH.1114480144784115')
        self.assertNotIn('to', payload)
        self.assertEqual(payload['template']['name'], 'account_statement')
        self.assertEqual(self.chat.messages.get(kind='statement').status, Message.SENT)


@override_settings(WHATSAPP_ACCESS_TOKEN='t', WHATSAPP_BUSINESS_ACCOUNT_ID='waba')
class SubmitTests(TestCase):

    def test_the_media_templates_go_with_a_sample_header(self):
        from django.core.management import call_command

        class Reply:
            def __init__(self, data, code=200):
                self._data, self.status_code, self.text = data, code, ''

            def json(self):
                return self._data

        posted = []

        def get(url, **kw):
            if url.endswith('/app'):
                return Reply({'id': 'app-9'})
            return Reply({'data': []})

        def post(url, **kw):
            if url.endswith('/uploads'):
                return Reply({'id': 'upload:abc'})
            if 'upload:abc' in url:
                return Reply({'h': 'handle-1'})
            posted.append(kw['json'])
            return Reply({'status': 'PENDING'})

        with patch('requests.get', side_effect=get), patch('requests.post', side_effect=post):
            call_command('whatsapp_templates', '--submit', stdout=open('/dev/null', 'w'))
        by_name = {p['name']: p for p in posted}
        receipt = by_name['receipt_ready']['components']
        self.assertEqual(receipt[0], {'type': 'HEADER', 'format': 'IMAGE', 'example': {'header_handle': ['handle-1']}})
        self.assertEqual(receipt[1]['text'].count('{{'), 2)
        self.assertEqual(by_name['account_statement']['components'][0]['format'], 'DOCUMENT')
        self.assertEqual(by_name['account_statement']['category'], 'UTILITY')
