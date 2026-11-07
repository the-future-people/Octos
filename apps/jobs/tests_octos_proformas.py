"""
Octos issues proformas (7 Nov 2026): priced through quote_line with add-ons
and sizes, issued as Octos, sent here as a PDF; and for a customer with no
record, the least details are asked for, then they are registered.
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.communications.models import Message
from apps.communications.tests import make_conversation, make_org
from apps.communications.tests_whatsapp_outbound import customer_wrote
from apps.jobs.models import PricingRule, Service

MEMORY = {**settings.STORAGES, 'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'}}
FAKE_PDF = b'%PDF-1.4 a proforma'


@override_settings(STORAGES=MEMORY)
class OctosProformaTests(TestCase):

    def setUp(self):
        self.branch = make_org()
        self.branch.is_trading = True
        self.branch.save()
        call_command('setup_octos', stdout=open('/dev/null', 'w'))
        self.prints = self.service('PRN2', 'A4 Printing (both sides)', '1.50', sides='DOUBLE')
        self.env = self.service('ENV-PACK-A4', 'A4 Brown Envelope (packed)', '2.00', unit='PER_PIECE')
        self.prints.addons.add(self.env)
        self.banner = self.service('FLX', 'Flexy Banner', '3.25', unit='PER_SQFT')
        self.conv = make_conversation(None, contact_phone='+233244000888')
        customer_wrote(self.conv, timedelta(minutes=2))

    def service(self, code, name, price, unit='sheet', sides='SINGLE'):
        s = Service.objects.create(code=code, name=name, category='INSTANT', unit=unit, is_active=True,
                                   smart_defaults={'sides': sides})
        PricingRule.objects.create(service=s, branch=None, base_price=Decimal(price), is_active=True)
        return s

    def send(self, lines, customer=None):
        from apps.communications.assistant import proformas
        with patch('apps.jobs.pdf.proforma_pdf.build_proforma_pdf', return_value=FAKE_PDF):
            return proformas.send_proforma(self.conv, lines, customer)

    def test_a_customer_with_no_record_is_asked_for_the_least_details(self):
        result = self.send([{'service_code': 'PRN2', 'quantity': 3, 'specifications': {'pages': 9}}])
        self.assertTrue(result['needs_customer_details'])

    def test_registered_then_issued_as_octos_and_sent_as_a_pdf(self):
        result = self.send(
            [{'service_code': 'PRN2', 'quantity': 3, 'specifications': {'pages': 9}, 'addon_codes': ['ENV-PACK-A4']},
             {'service_code': 'FLX', 'quantity': 1, 'specifications': {'width_in': 72, 'height_in': 36}}],
            {'company_name': 'Accra Academy', 'contact_person': 'Mr Kofi Mensah'})
        # 9 pages both sides = 5 sheets x 1.50 x 3 = 22.50, one envelope for all = 2.00;
        # a 72 x 36 in banner = 18 sq ft x 3.25 = 58.50. Total 83.00.
        self.assertEqual(result['total'], 'GHS 83.00')
        from apps.jobs.models import ProformaInvoice
        proforma = ProformaInvoice.objects.get(proforma_number=result['proforma'])
        self.assertEqual(proforma.issued_by.email, 'octos@octos.internal')
        self.assertEqual(proforma.status, ProformaInvoice.Status.ISSUED)
        self.assertEqual(proforma.customer.company_name, 'Accra Academy')
        self.conv.refresh_from_db()
        self.assertEqual(self.conv.customer_id, proforma.customer_id)
        sent = self.conv.messages.get(message_type=Message.DOCUMENT)
        self.assertEqual((sent.media_mime, sent.media_name), ('application/pdf', f"{result['proforma']}.pdf"))
        self.assertIn(result['proforma'], sent.body)

    def test_a_known_customer_is_not_asked_again(self):
        from apps.customers.models import CustomerProfile
        CustomerProfile.objects.create(phone='+233244000888', first_name='Ama', last_name='Owusu',
                                       customer_type='INDIVIDUAL')
        result = self.send([{'service_code': 'PRN2', 'quantity': 1, 'specifications': {'pages': 10}}])
        self.assertEqual(result['total'], 'GHS 7.50')   # 5 sheets x 1.50

    def test_the_octos_account_cannot_sign_in(self):
        from django.contrib.auth import get_user_model
        octos = get_user_model().objects.get(email='octos@octos.internal')
        self.assertFalse(octos.has_usable_password())
        self.assertFalse(octos.is_active)
