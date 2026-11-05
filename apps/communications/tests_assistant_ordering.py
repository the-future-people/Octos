"""
Octos's ordering tools: the order built from the chat on the storefront's
own foundations (inspection, pricing, payment), and every guard on it.
"""
import io
from decimal import Decimal
from unittest.mock import patch

from django.conf import settings
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from pypdf import PdfWriter

from apps.communications.assistant import ordering
from apps.communications.models import Message
from apps.communications.tests import make_conversation, make_org
from apps.jobs.models import PricingRule, Service
from apps.jobs.services.availability import sheets_for
from apps.storefront.models import OnlineOrder
from apps.storefront.services.pricing import price_lines

MEMORY = {**settings.STORAGES, 'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'}}
PAGES = [{'key': 'pages', 'type': 'number', 'label': 'Pages', 'required': True}]


def pdf(pages):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


@override_settings(STORAGES=MEMORY)
class OrderingTests(TestCase):

    def setUp(self):
        self.branch = make_org()
        self.branch.is_trading = True
        self.branch.save()
        self.printing = Service.objects.create(
            code='T-A4BW', name='Test A4 Black and White', category='INSTANT', unit='sheet',
            is_active=True, requires_file_upload=True, spec_template=PAGES,
        )
        PricingRule.objects.create(service=self.printing, branch=None, base_price=Decimal('1.00'), is_active=True)
        self.conv = make_conversation(None, contact_phone='+233244800801', contact_name='Ama Boateng')
        self.file = self.sent_file(self.conv, pdf(3))

    def sent_file(self, conv, content):
        msg = Message.objects.create(conversation=conv, direction=Message.INBOUND, channel=Message.WHATSAPP,
                                     message_type=Message.DOCUMENT, body='', media_id='m-1',
                                     media_name='report.pdf', media_mime='application/pdf', media_pages=3)
        msg.media_file.save('report.pdf', ContentFile(content), save=False)
        Message.objects.filter(pk=msg.pk).update(media_file=msg.media_file.name)
        msg.refresh_from_db()
        return msg

    def prepare(self, **kwargs):
        lines = kwargs.pop('lines', [{'service_code': 'T-A4BW', 'quantity': 2, 'file': self.file.pk}])
        return ordering.prepare_order(self.conv, lines, branches=[self.branch], **kwargs)

    def test_an_order_priced_from_the_files_own_pages(self):
        result = self.prepare()
        self.assertTrue(result['success'], result)
        order = OnlineOrder.objects.get(order_number=result['order'])
        (line,) = order.line_items
        self.assertEqual(line['specifications']['pages'], sheets_for(self.printing, 3))
        expected = price_lines([{'service': self.printing.pk, 'quantity': 2,
                                 'specifications': {'pages': sheets_for(self.printing, 3)}, 'addons': []}])[1]
        self.assertEqual(result['total'], f'GHS {expected:.2f}')
        self.assertEqual(order.files.count(), 1)
        self.assertEqual(order.lead.first_name, 'Ama')

    def test_a_service_that_needs_a_file_cant_be_ordered_without_one(self):
        result = self.prepare(lines=[{'service_code': 'T-A4BW', 'quantity': 1}])
        self.assertFalse(result['success'])
        self.assertIn("needs the customer's file", result['error'])

    def test_a_file_from_another_conversation_is_never_used(self):
        other = make_conversation(None, contact_phone='+233244800802')
        theirs = self.sent_file(other, pdf(1))
        result = self.prepare(lines=[{'service_code': 'T-A4BW', 'quantity': 1, 'file': theirs.pk}])
        self.assertFalse(result['success'])
        self.assertFalse(OnlineOrder.objects.exists())

    @patch('apps.jobs.services.file_checks.check_file', return_value={'verdict': 'warn', 'checks': ['May print soft']})
    def test_a_warned_file_waits_for_the_customer_then_goes_ahead(self, _check):
        first = self.prepare()
        self.assertTrue(first['needs_customer_ok'])
        self.assertFalse(OnlineOrder.objects.exists())
        second = self.prepare(accept_warnings=True)
        self.assertTrue(second['success'])
        self.assertTrue(OnlineOrder.objects.get(order_number=second['order']).files.get().warning_accepted)

    @patch('apps.jobs.services.file_checks.check_file', return_value={'verdict': 'refuse', 'checks': ['Too small to print']})
    def test_a_refused_file_stops_the_order(self, _check):
        result = self.prepare()
        self.assertTrue(result['file_refused'])
        self.assertFalse(OnlineOrder.objects.exists())

    def test_the_payment_link_uses_the_pay_buttons_path(self):
        order_number = self.prepare()['order']
        with patch('apps.storefront.services.paystack.initialise',
                   return_value={'success': True, 'authorization_url': 'https://checkout.paystack.com/abc',
                                 'reference': 'REF-1'}):
            result = ordering.send_payment_link(self.conv, order_number)
        self.assertEqual(result['link'], 'https://checkout.paystack.com/abc')
        order = OnlineOrder.objects.get(order_number=order_number)
        self.assertEqual(order.status, OnlineOrder.Status.AWAITING_PAYMENT)

    def test_no_link_for_someone_elses_order(self):
        order_number = self.prepare()['order']
        stranger = make_conversation(None, contact_phone='+233244800899')
        self.assertFalse(ordering.send_payment_link(stranger, order_number)['success'])