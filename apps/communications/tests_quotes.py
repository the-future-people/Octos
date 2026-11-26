"""
A quote from the inbox (25 Nov 2026): priced as it is built, then sent with
a payment link, for the counter with a pickup code, or as a proforma, on
the same foundations as Octos's own orders. And the fix found on the way:
an order Octos just prepared can go straight to the counter.
"""
import io
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from pypdf import PdfReader, PdfWriter
from rest_framework.test import APIClient

from apps.communications.assistant import ordering
from apps.communications.models import Message
from apps.communications.services import quotes
from apps.communications.tests import make_conversation, make_org, make_user
from apps.communications.tests_whatsapp_outbound import customer_wrote
from apps.jobs.models import Job, PricingRule, Service
from apps.storefront.models import OnlineOrder

MEMORY = {**settings.STORAGES, 'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'}}
PAGES = [{'key': 'pages', 'type': 'number', 'label': 'Pages', 'required': True}]
PAYSTACK = {'success': True, 'authorization_url': 'https://checkout.paystack.com/q1', 'reference': 'REF-Q1'}


def pdf(pages):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


@override_settings(STORAGES=MEMORY)
class QuoteTests(TestCase):

    def setUp(self):
        self.branch = make_org()
        self.branch.is_trading = True
        self.branch.save()
        self.staff = make_user('esi@farhat.test', self.branch)
        self.staff.first_name, self.staff.last_name = 'Esi', 'Mensah'
        self.staff.save()
        self.colour = self.service('T-A4COL', 'Test A4 Colour', '2.50', requires_file_upload=True,
                                   spec_template=PAGES)
        self.envelope = self.service('T-ENV', 'Test Brown Envelope', '2.00', unit='PER_PIECE')
        self.colour.addons.add(self.envelope)
        self.conv = make_conversation(None, contact_phone='+233244800901', contact_name='Loretta Mensah')
        customer_wrote(self.conv, timedelta(minutes=2))
        self.file = self.sent_file(pdf(4))

    def service(self, code, name, price, unit='sheet', **fields):
        s = Service.objects.create(code=code, name=name, category='INSTANT', unit=unit, is_active=True, **fields)
        PricingRule.objects.create(service=s, branch=None, base_price=Decimal(price), is_active=True)
        return s

    def sent_file(self, content):
        msg = Message.objects.create(conversation=self.conv, direction=Message.INBOUND, channel=Message.WHATSAPP,
                                     message_type=Message.DOCUMENT, body='', media_id='m-q1',
                                     media_name='exams.pdf', media_mime='application/pdf', media_pages=4)
        msg.media_file.save('exams.pdf', ContentFile(content), save=False)
        Message.objects.filter(pk=msg.pk).update(media_file=msg.media_file.name)
        msg.refresh_from_db()
        return msg

    def lines(self, copies=3, envelope=True):
        return [{'service_code': 'T-A4COL', 'quantity': copies, 'file': self.file.pk,
                 'addon_codes': ['T-ENV'] if envelope else []}]

    def send(self, how='link', **kwargs):
        with patch('apps.storefront.services.paystack.initialise', return_value=PAYSTACK):
            return quotes.send(self.conv, self.staff, kwargs.pop('lines', self.lines()), how, **kwargs)

    # ── The price while it's built ──

    def test_the_preview_prices_like_the_order_and_saves_nothing(self):
        result = quotes.preview(self.conv, self.lines())
        # 4 pages from the file x 3 copies x 2.50 = 30.00; an envelope each, 3 x 2.00 = 6.00.
        self.assertEqual(result['total'], '36.00', result)
        (line,) = result['lines']
        self.assertEqual((line['pages'], line['price']), (4, '30.00'))
        self.assertEqual(line['addons'][0]['price'], '6.00')
        self.assertFalse(OnlineOrder.objects.exists())

    def test_the_preview_says_what_is_missing(self):
        result = quotes.preview(self.conv, [{'service_code': 'NOPE', 'quantity': 1}])
        self.assertIn('pick a service', result['error'])

    def test_the_catalogue_lists_what_can_be_quoted_with_its_add_ons(self):
        found = {s['code']: s for s in quotes.catalogue()}
        self.assertEqual(found['T-A4COL']['addons'], [{'code': 'T-ENV', 'name': 'Test Brown Envelope'}])
        self.assertTrue(found['T-A4COL']['counts_pages'])

    # ── Sending it ──

    def test_with_a_payment_link_and_the_pdf(self):
        result = self.send('link')
        self.assertTrue(result['success'], result)
        order = OnlineOrder.objects.get(order_number=result['order'])
        self.assertEqual(order.status, OnlineOrder.Status.AWAITING_PAYMENT)
        self.assertIn('Taken by Octos on WhatsApp', order.notes)          # reminders and the desk find it
        self.assertIn('Quoted by Esi Mensah in the inbox', order.notes)
        paper, quote = result['messages']
        self.assertEqual((paper.kind, paper.message_type, paper.media_name),
                         (quotes.PDF_KIND, Message.DOCUMENT, f'Quote {order.order_number}.pdf'))
        self.assertEqual(quote.kind, quotes.KIND)
        self.assertEqual(quote.sent_by, self.staff)
        self.assertIn("Here's your quote, Loretta", quote.body)
        self.assertIn('*Total: GHS 36.00*', quote.body)
        self.assertIn('https://checkout.paystack.com/q1', quote.body)
        self.assertEqual(Message.objects.filter(order=order).count(), 2)
        self.conv.refresh_from_db()
        self.assertEqual(self.conv.assigned_to, self.staff)              # a quote is a reply

    def test_the_pdf_is_left_off_when_unticked(self):
        result = self.send('link', pdf=False)
        self.assertEqual([m.kind for m in result['messages']], [quotes.KIND])

    def test_for_the_counter_with_a_pickup_code(self):
        result = self.send('counter')
        self.assertTrue(result['success'], result)
        job = Job.objects.get(counter_code=result['code'])
        self.assertEqual(job.status, Job.AWAITING_ARRIVAL)
        self.assertFalse(job.print_ahead)                    # someone new: printed when they come
        quote = result['messages'][-1]
        self.assertIn(f"pickup code is *{result['code']}*", quote.body)
        self.assertIn("We'll print it as soon as you arrive", quote.body)
        self.assertNotIn('paystack', quote.body)

    def test_the_card_follows_the_order(self):
        from apps.communications.api.serializers import MessageSerializer
        quote = self.send('link')['messages'][-1]
        card = MessageSerializer(Message.objects.get(pk=quote.pk)).data['quote']
        self.assertEqual((card['state'], card['label'], card['total']), ('waiting', 'Waiting to pay', '36.00'))
        from django.utils import timezone
        OnlineOrder.objects.filter(pk=quote.order_id).update(status=OnlineOrder.Status.PAID, paid_at=timezone.now())
        card = MessageSerializer(Message.objects.get(pk=quote.pk)).data['quote']
        self.assertEqual((card['state'], card['label']), ('paid', 'Paid · GHS 36.00'))

    def test_the_counter_card_shows_the_code(self):
        from apps.communications.api.serializers import MessageSerializer
        result = self.send('counter', pdf=False)
        card = MessageSerializer(Message.objects.get(pk=result['messages'][-1].pk)).data['quote']
        self.assertEqual(card['state'], 'counter')
        self.assertEqual(card['label'], f"Pays at the counter · code {result['code']}")

    def test_nothing_is_made_when_the_window_is_closed(self):
        Message.objects.filter(conversation=self.conv, direction=Message.INBOUND).update(
            created_at=self.conv.created_at - timedelta(days=3))
        with patch('apps.communications.services.window.window_open', return_value=False):
            result = self.send('link')
        self.assertIn('Free replies are closed', result['error'])
        self.assertFalse(OnlineOrder.objects.exists())

    def test_a_hidden_number_is_asked_for_first(self):
        self.conv.contact_phone = ''
        self.conv.save()
        with patch('apps.communications.services.window.window_open', return_value=True):
            result = self.send('link')
        self.assertIn('number is hidden', result['error'])

    def test_as_a_proforma_issued_by_octos_sent_by_the_person(self):
        call_command('setup_octos', stdout=open('/dev/null', 'w'))
        lines = [{'service_code': 'T-A4COL', 'quantity': 3, 'specifications': {'pages': 4}}]
        with patch('apps.jobs.pdf.proforma_pdf.build_proforma_pdf', return_value=b'%PDF-1.4 p'):
            first = self.send('proforma', lines=lines)
            self.assertTrue(first['needs_customer_details'])
            result = self.send('proforma', lines=lines, customer={'first_name': 'Loretta', 'last_name': 'Mensah'})
        self.assertTrue(result['success'], result)
        from apps.jobs.models import ProformaInvoice
        proforma = ProformaInvoice.objects.get(proforma_number=result['proforma'])
        self.assertEqual(proforma.issued_by.email, 'octos@octos.internal')
        self.assertIn('Esi Mensah', proforma.notes)
        sent = self.conv.messages.get(kind='proforma')
        self.assertEqual(sent.sent_by, self.staff)

    def test_the_quote_pdf_is_a_real_one_page_document(self):
        from apps.jobs.pdf.quote_pdf import build_quote_pdf
        result = self.send('link', pdf=False)
        order = OnlineOrder.objects.get(order_number=result['order'])
        content = build_quote_pdf(order, name='Loretta Mensah', phone='+233244800901', ready='about 3:40pm today')
        reader = PdfReader(io.BytesIO(content))
        text = reader.pages[0].extract_text()
        self.assertEqual(len(reader.pages), 1)
        self.assertIn(order.order_number, text)
        self.assertIn('GHS 36.00', text)
        self.assertIn('Test Brown Envelope', text)

    # ── The API ──

    def test_the_api_prices_and_sends(self):
        api = APIClient()
        api.force_authenticate(self.staff)
        priced = api.post(f'/api/v1/communications/{self.conv.pk}/quote/price/', {'lines': self.lines()},
                          format='json')
        self.assertEqual((priced.status_code, priced.data['total']), (200, '36.00'))
        with patch('apps.storefront.services.paystack.initialise', return_value=PAYSTACK):
            sent = api.post(f'/api/v1/communications/{self.conv.pk}/quote/send/',
                            {'lines': self.lines(), 'how': 'link', 'pdf': False}, format='json')
        self.assertEqual(sent.status_code, 201, sent.data)
        self.assertEqual(sent.data['messages'][0]['quote']['state'], 'waiting')
        services = api.get('/api/v1/communications/quote/services/')
        self.assertIn('T-A4COL', [s['code'] for s in services.data['services']])

    def test_a_proforma_for_someone_new_asks_for_their_name(self):
        api = APIClient()
        api.force_authenticate(self.staff)
        call_command('setup_octos', stdout=open('/dev/null', 'w'))
        sent = api.post(f'/api/v1/communications/{self.conv.pk}/quote/send/',
                        {'lines': self.lines(envelope=False), 'how': 'proforma'}, format='json')
        self.assertEqual(sent.status_code, 409)
        self.assertTrue(sent.data['needs_customer'])

    # ── Found on the way ──

    def test_an_order_octos_just_prepared_can_go_straight_to_the_counter(self):
        """reserve() took only orders a link had gone out for, so "I'll pay when I come" was refused."""
        prepared = ordering.prepare_order(self.conv, self.lines(), branches=[self.branch])
        self.assertEqual(OnlineOrder.objects.get(order_number=prepared['order']).status, OnlineOrder.Status.DRAFT)
        result = ordering.pay_at_counter(self.conv, prepared['order'])
        self.assertTrue(result['success'], result)
        self.assertEqual(OnlineOrder.objects.get(order_number=prepared['order']).status,
                         OnlineOrder.Status.COUNTER)
