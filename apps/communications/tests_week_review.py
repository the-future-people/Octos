"""
Fixes from reading a week of chats (14 to 20 Nov 2026), one class each:

  names          "The", "Osekre01" and an email never greeted; "I'm not Mary" remembered
  one order      a changed order replaces the chat's earlier one; one payment reminder a chat
  the clock      a staff reminder counts from when a person got the chat
  quiet files    a job or receipt that day counts; Octos follows up once, from the chat, before staff
  take-backs     proof the team dealt with it keeps Octos quiet; otherwise he answers from the chat
  reading files  Octos opens PDFs, Word files and photos for the boss
  voice notes    "could you type it", once a visit
  regulars       a customer Farhat knows is welcomed back like one, never the same words twice
  softer         "prints softer" only for photos and big prints
"""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from apps.communications.assistant import counter, ordering, prompt
from apps.communications.models import AssistantRun, Conversation, Message
from apps.communications.services import chat_customer, handover, names
from apps.communications.services.quiet_remote import flag_quiet
from apps.communications.tests import make_conversation, make_job, make_org
from apps.communications.tests_assistant_ordering import MEMORY, PAGES, pdf
from apps.customers.models import CustomerProfile
from apps.jobs.models import Job, PricingRule, Service
from apps.spine import kinds
from apps.spine.models import Event, Visit
from apps.spine.recorder import record
from apps.storefront.models import Lead, OnlineOrder
from apps.storefront.services import payment_reminder, thanks
from apps.storefront.services.welcome import first_name, welcome_text


def inbound(chat, body='', ago=None, **fields):
    m = Message.objects.create(conversation=chat, direction=Message.INBOUND, channel=Message.WHATSAPP,
                               body=body, **fields)
    if ago is not None:
        Message.objects.filter(pk=m.pk).update(created_at=timezone.now() - ago)
        m.refresh_from_db()
    return m


class NameCheckTests(SimpleTestCase):

    def test_what_the_week_greeted_gives_no_name(self):
        for profile in ('The', '.', 'A', 'Osekre01', 'doedominic2010@gmail.com', 'Nik_cage..⚓️', 'GOD',
                        'Pingfenceenterprise', "PEOPLE'S KOFI", 'Kings Hub Ventures', 'lil.livelle👻💗',
                        'Walk-in Customer', 'Customer', ''):
            self.assertEqual(names.first_name_from(profile), '', profile)

    def test_real_names_still_greet(self):
        self.assertEqual(names.first_name_from('Mr Silas Kyeremanteg'), 'Silas')
        self.assertEqual(names.first_name_from('AKOSUA MENSAH'), 'Akosua')
        self.assertEqual(names.first_name_from('Mss. Grace Adjorkor'), 'Grace')
        self.assertEqual(names.first_name_from('Noel'), 'Noel')
        self.assertEqual(names.first_name_from("Nana Ama O'Neil"), 'Ama')

    def test_the_welcome_uses_the_same_checker(self):
        self.assertEqual(first_name('Osekre01'), '')
        self.assertTrue(welcome_text('The').startswith('Welcome to'))
        self.assertTrue(welcome_text('Kofi Asante').startswith('Hi Kofi, welcome'))


class NameCorrectionTests(TestCase):

    def setUp(self):
        make_org('-NM')
        self.customer = CustomerProfile.objects.create(first_name='Mary', phone='+233244771001',
                                                       customer_type='INDIVIDUAL')
        self.chat = make_conversation(None, contact_phone='+233244771001', contact_name='Mary',
                                      customer=self.customer)

    def said(self, text):
        return names.note_correction(self.chat, inbound(self.chat, text))

    def test_im_not_mary_is_never_used_again(self):
        self.assertEqual(names.name_for(self.chat), 'Mary')
        self.assertEqual(self.said("Please I'm not Mary"), {'refused': 'Mary'})
        self.assertEqual(names.name_for(self.chat), '')
        self.assertEqual(names.name_for(customer=self.customer), '')
        self.assertEqual(first_name(self.customer), '')
        self.assertEqual(counter._first_name(self.chat), '')

    def test_the_evening_thank_you_drops_the_wrong_name(self):
        self.said("I'm not Mary")
        self.assertNotIn('Mary', thanks.thanks_text(self.customer, timezone.localdate()))

    def test_the_name_they_give_is_used_and_kept_on_their_record(self):
        self.assertEqual(self.said("It's Akos not Mary"), {'refused': 'Mary'})
        self.assertEqual(self.said('My name is Akos'), {'preferred': 'Akos'})
        self.assertEqual(names.name_for(self.chat), 'Akos')
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.first_name, 'Akos')

    def test_ordinary_sentences_are_not_corrections(self):
        for text in ("I'm not sure", 'call me later', 'call me when it is ready', 'not now please',
                     'Is it not ready?', "My name isn't important"):
            self.assertIsNone(self.said(text), text)
        self.assertEqual(names.name_for(self.chat), 'Mary')

    def test_call_me_with_a_name(self):
        self.assertEqual(self.said('You can call me Esi'), {'preferred': 'Esi'})
        self.assertEqual(names.name_for(self.chat), 'Esi')

    def test_octos_is_told_and_says_sorry(self):
        self.said("I'm not Mary")
        line = prompt._customer_line(self.chat)
        self.assertIn('their name is not Mary', line)
        self.assertIn('say sorry once', line)
        self.assertNotIn('talking to Mary', line)

    def test_save_customer_name_on_a_known_chat_is_remembered(self):
        from apps.communications.assistant import brain
        ctx = SimpleNamespace(conversation=self.chat)
        result = brain._run_tool('save_customer_name', {'first_name': 'Akos'}, ctx)
        self.assertEqual(result['saved'], 'Akos')
        self.assertEqual(names.name_for(self.chat), 'Akos')

    def test_the_webhook_notes_it(self):
        from apps.communications.services import whatsapp_inbound
        with patch.object(whatsapp_inbound, 'wake_octos'):
            whatsapp_inbound._receive({'id': 'wamid.mary1', 'from': '233244771001', 'type': 'text',
                                       'text': {'body': "Hello, I'm not Mary"}}, 'Mary')
        self.assertTrue(Event.objects.filter(kind=kinds.NAME_CORRECTED, payload__refused='Mary').exists())


class NewChatCustomerTests(TestCase):

    def setUp(self):
        self.branch = make_org('-NC')

    def test_a_profile_that_is_no_name_gives_a_record_with_no_name(self):
        chat = make_conversation(None, contact_phone='+233244771002', contact_name='The')
        customer, created = chat_customer.customer_for_chat(chat)
        self.assertTrue(created)
        self.assertEqual(customer.first_name, '')

    def test_a_real_name_is_kept(self):
        chat = make_conversation(None, contact_phone='+233244771003', contact_name='Loretta Owusu')
        customer, _ = chat_customer.customer_for_chat(chat)
        self.assertEqual(customer.first_name, 'Loretta')

    def test_a_receipt_for_a_whatsapp_label_has_no_handle(self):
        from apps.finance.services.receipt_image import receipt_data
        branch = self.branch
        chat = make_conversation(None, contact_phone='+233244771004', contact_name='Osekre01')
        job = make_job(branch)
        Job.objects.filter(pk=job.pk).update(estimated_cost=Decimal('5'))
        job.refresh_from_db()
        chat.jobs.add(job)
        receipt = SimpleNamespace(job=job, customer_name='Osekre01 (WhatsApp)', created_at=timezone.now(),
                                  branch=branch, payment_method='CASH', receipt_number='RCP-1',
                                  amount_paid=Decimal('5'), balance_due=Decimal('0'), cashier=None,
                                  get_payment_method_display=lambda: 'Cash')
        self.assertEqual(receipt_data(receipt)['first_name'], '')
        receipt.customer_name = 'Mr Silas Kyeremanteg'                 # typed at the counter: kept
        self.assertEqual(receipt_data(receipt)['first_name'], 'Silas')


@override_settings(STORAGES=MEMORY)
class OneOrderPerChatTests(TestCase):

    def setUp(self):
        self.branch = make_org('-OO')
        self.branch.is_trading = True
        self.branch.save()
        self.printing = Service.objects.create(
            code='T-A4BW-W', name='Test A4 Black and White W', category='INSTANT', unit='sheet',
            is_active=True, requires_file_upload=True, spec_template=PAGES)
        PricingRule.objects.create(service=self.printing, branch=None, base_price=Decimal('1.00'), is_active=True)
        self.chat = make_conversation(None, contact_phone='+233244771010', contact_name='Kings Hub Ventures')
        from django.core.files.base import ContentFile
        msg = inbound(self.chat, message_type=Message.DOCUMENT, media_id='m-w1', media_name='doc.pdf',
                      media_mime='application/pdf', media_pages=2)
        msg.media_file.save('doc.pdf', ContentFile(pdf(2)), save=False)
        Message.objects.filter(pk=msg.pk).update(media_file=msg.media_file.name)
        self.file = msg

    def prepare(self, quantity):
        return ordering.prepare_order(self.chat, [{'service_code': 'T-A4BW-W', 'quantity': quantity,
                                                   'file': self.file.pk}], branches=[self.branch])

    def test_a_changed_order_replaces_the_earlier_one(self):
        first = self.prepare(2)
        second = self.prepare(3)
        self.assertEqual(second['replaces'], [first['order']])
        self.assertEqual(OnlineOrder.objects.get(order_number=first['order']).status, OnlineOrder.Status.ABANDONED)
        self.assertEqual(OnlineOrder.objects.get(order_number=second['order']).status, OnlineOrder.Status.DRAFT)

    def test_an_order_with_a_link_out_is_never_touched_and_octos_is_told(self):
        first = self.prepare(2)
        OnlineOrder.objects.filter(order_number=first['order']).update(status=OnlineOrder.Status.AWAITING_PAYMENT)
        second = self.prepare(3)
        self.assertEqual(second['earlier_link_still_open'], [first['order']])
        self.assertIn('use only the new one', second['tell_them'])
        self.assertEqual(OnlineOrder.objects.get(order_number=first['order']).status,
                         OnlineOrder.Status.AWAITING_PAYMENT)

    def test_the_lead_gets_no_business_name(self):
        first = self.prepare(1)
        self.assertEqual(OnlineOrder.objects.get(order_number=first['order']).lead.first_name, 'Customer')


class OneReminderPerChatTests(TestCase):

    def setUp(self):
        self.branch = make_org('-PR')
        self.branch.is_trading = True
        self.branch.save()
        self.chat = make_conversation(None, contact_phone='+233244771020')
        inbound(self.chat, 'Hi', ago=timedelta(hours=4))
        lead = Lead.objects.create(phone='+233244771020', first_name='Kofi')
        self.orders = []
        for n, hours in enumerate((3, 2.5)):
            order = OnlineOrder.objects.create(
                lead=lead, branch=self.branch, status=OnlineOrder.Status.AWAITING_PAYMENT, total=Decimal('45.00'),
                line_items=[{'service_name': 'Stickers', 'quantity': 10, 'total': '45.00'}],
                notes=f'Taken by Octos on WhatsApp (conversation {self.chat.pk})')
            OnlineOrder.objects.filter(pk=order.pk).update(
                updated_at=timezone.now() - timedelta(hours=hours),
                created_at=timezone.now() - timedelta(hours=hours, minutes=5))
            self.orders.append(order)
        for p in (patch('apps.organization.services.hours.is_open', return_value=True),
                  patch('apps.notifications.services.notify_many')):
            p.start()
            self.addCleanup(p.stop)

    def test_only_the_newest_order_is_asked_about_and_only_once(self):
        self.assertEqual(payment_reminder.remind_all(), 1)
        self.assertEqual(self.chat.messages.filter(kind=payment_reminder.KIND).count(), 1)
        self.assertEqual(payment_reminder.remind_all(), 0)
        for order in self.orders:
            order.refresh_from_db()
            self.assertIsNotNone(order.payment_reminded_at)

    def test_a_name_refused_in_the_chat_is_not_used(self):
        names.note_correction(self.chat, inbound(self.chat, "I'm not Kofi", ago=timedelta(hours=4)))
        self.assertTrue(payment_reminder.reminder_text(self.orders[1]).startswith('Hi, your'))


class ReminderClockTests(TestCase):

    def setUp(self):
        make_org('-CL')
        self.chat = make_conversation(None, contact_phone='+233244771030')
        inbound(self.chat, message_type=Message.IMAGE, media_id='m-c1', ago=timedelta(minutes=33))
        p = patch('apps.notifications.services.notify_many')
        p.start()
        self.addCleanup(p.stop)
        q = patch('apps.communications.services.owner_line.customer_waiting')
        self.owner = q.start()
        self.addCleanup(q.stop)

    def test_a_handover_after_33_minutes_is_not_reminded_a_minute_later(self):
        handover.octos_hands_over(self.chat, 'went quiet')
        self.assertEqual(handover.watch(timezone.now() + timedelta(minutes=1)), (0, 0))
        reminded, _ = handover.watch(timezone.now() + timedelta(minutes=31))
        self.assertEqual(reminded, 1)
        self.assertEqual(self.owner.call_args.args[1], 64)       # still says how long they really waited

    def test_taking_it_over_after_the_reminder_never_reminds_again_at_once(self):
        handover.octos_hands_over(self.chat, 'went quiet')
        handover.watch(timezone.now() + timedelta(minutes=31))
        from apps.communications.tests import make_user
        user = make_user('noel-clock@example.com', None)
        handover.take_over(self.chat, user)
        self.assertEqual(handover.watch(timezone.now() + timedelta(minutes=2)), (0, 0))
        self.assertEqual(handover.watch(timezone.now() + timedelta(minutes=31))[0], 1)


@override_settings(OCTOS_ASSISTANT_MODE='live', ANTHROPIC_API_KEY='test-key')
class QuietFileTests(TestCase):

    def setUp(self):
        self.branch = make_org('-QF')
        noel = CustomerProfile.objects.create(first_name='Noel', phone='+233244771040', customer_type='INDIVIDUAL')
        self.chat = make_conversation(None, contact_phone='+233244771040', contact_name='Noel', customer=noel)
        self.now = timezone.now()
        for p in (patch('apps.communications.assistant.counter.shop_open', return_value=True),
                  patch('apps.notifications.services.notify_many')):
            p.start()
            self.addCleanup(p.stop)

    def sent_file(self, minutes_ago):
        inbound(self.chat, message_type=Message.IMAGE, media_id=f'm-q{minutes_ago}', ago=timedelta(minutes=minutes_ago))
        record(kinds.MESSAGE_RECEIVED, actor=Event.CUSTOMER, conversation=self.chat,
               occurred_at=self.now - timedelta(minutes=minutes_ago), key=f'wa:qf-{minutes_ago}',
               payload={'has_file': True})
        return Visit.objects.get(conversation=self.chat, closed_at__isnull=True)

    def follow_up_says(self, words):
        from apps.communications.tests_assistant_brain import Model, says, text
        return patch('anthropic.Anthropic', return_value=Model(says(text(words))))

    def octos_said(self):
        return list(self.chat.messages.filter(direction=Message.OUTBOUND, is_internal_note=False)
                    .values_list('body', flat=True))

    def test_octos_follows_up_once_from_the_chat_before_a_person_is_brought_in(self):
        self.sent_file(40)
        with self.follow_up_says('Would you like the poster printed on A3, like last time?') as model:
            self.assertEqual(flag_quiet(self.now), 0)
        system = str(model.return_value.calls[0]['system'])
        self.assertIn('never a general "just checking in"', system)
        self.assertEqual(self.octos_said(), ['Would you like the poster printed on A3, like last time?'])
        self.chat.refresh_from_db()
        self.assertEqual(self.chat.handled_by, Conversation.OCTOS)
        self.assertEqual(flag_quiet(self.now + timedelta(minutes=10)), 0)      # his message restarted the clock
        self.assertEqual(flag_quiet(self.now + timedelta(minutes=31)), 1)      # still nothing: a person
        self.assertEqual(len(self.octos_said()), 1)                           # one follow-up, ever

    def test_when_the_chat_needs_nothing_octos_says_nothing_and_nobody_is_called(self):
        self.sent_file(40)
        with self.follow_up_says(''):
            self.assertEqual(flag_quiet(self.now), 0)
        self.assertEqual(self.octos_said(), [])
        self.assertEqual(flag_quiet(self.now + timedelta(minutes=31)), 0)
        self.chat.refresh_from_db()
        self.assertEqual(self.chat.handled_by, Conversation.OCTOS)

    def test_a_teammate_sending_a_file_back_is_proof(self):
        from apps.communications.tests import make_user
        self.sent_file(40)
        Message.objects.create(conversation=self.chat, direction=Message.OUTBOUND, channel=Message.WHATSAPP,
                               message_type=Message.DOCUMENT, media_id='m-back', media_name='corrected.pdf',
                               sent_by=make_user('kingsford-qf@example.com', self.branch))
        with self.follow_up_says('should not be asked') as model:
            self.assertEqual(flag_quiet(self.now), 0)
        self.assertEqual(model.return_value.calls, [])
        self.assertEqual(flag_quiet(self.now + timedelta(minutes=31)), 0)

    def test_a_job_made_earlier_the_same_day_counts(self):
        # Osekre: job and receipt, then a corrected copy of the file opened a new visit.
        job = make_job(self.branch)
        self.chat.jobs.add(job)
        Job.objects.filter(pk=job.pk).update(created_at=timezone.localtime(self.now).replace(hour=0, minute=5))
        visit = self.sent_file(40)
        Visit.objects.filter(pk=visit.pk).update(opened_at=self.now - timedelta(minutes=40))
        self.assertEqual(flag_quiet(self.now), 0)
        self.assertEqual(self.octos_said(), [])


class TakeBackTests(TestCase):

    def setUp(self):
        self.branch = make_org('-TB')
        self.chat = make_conversation(None, contact_phone='+233244771050', contact_name='Noel')
        self.photo = inbound(self.chat, message_type=Message.IMAGE, media_id='m-tb1', ago=timedelta(minutes=45))
        record(kinds.OCTOS_TOOK_BACK, actor=Event.OCTOS, conversation=self.chat)

    def step(self):
        with patch('apps.communications.services.opened.in_focus', return_value=False), \
                patch('apps.communications.assistant.counter.shop_open', return_value=True):
            return counter.step(self.chat, self.photo, timezone.now())

    def test_no_proof_goes_to_octos_with_the_chat_never_a_stock_line(self):
        self.assertIsNone(self.step())
        from apps.communications.assistant import brain
        self.assertIn('picking it up for the team', brain.TAKEN_BACK_NOTE)
        self.assertIn('never send a general check-in', brain.TAKEN_BACK_NOTE)

    def test_a_receipt_after_the_file_is_proof(self):
        Message.objects.create(conversation=self.chat, direction=Message.OUTBOUND, channel=Message.WHATSAPP,
                               kind='receipt', body="Here's your receipt")
        self.assertEqual(self.step(), (None, 'taken back, but the team dealt with it: their receipt was sent'))

    def test_a_job_after_the_file_is_proof(self):
        job = make_job(self.branch)
        self.chat.jobs.add(job)
        said, why = self.step()
        self.assertIsNone(said)
        self.assertIn(f'job {job.job_number} was made', why)

    def test_opening_the_file_is_not_proof(self):
        record(kinds.FILE_OPENED, actor=Event.STAFF, conversation=self.chat,
               occurred_at=timezone.now() - timedelta(minutes=40))
        self.assertIsNone(self.step())


class FileReadingTests(TestCase):

    def setUp(self):
        self.branch = make_org('-FR')
        self.chat = make_conversation(None, contact_phone='+233244771090', contact_name='Amoree')

    def sent(self, name, mime, content, mtype=Message.DOCUMENT):
        from django.core.files.base import ContentFile
        m = Message.objects.create(conversation=self.chat, direction=Message.OUTBOUND, channel=Message.WHATSAPP,
                                   message_type=mtype, media_name=name, media_mime=mime)
        m.media_file.save(name, ContentFile(content), save=True)
        return m

    def table_pdf(self):
        from reportlab.pdfgen import canvas
        import io
        out = io.BytesIO()
        c = canvas.Canvas(out)
        c.drawString(72, 720, 'No. 9  Kwame Mensah  1983')
        c.save()
        return out.getvalue()

    def test_the_boss_can_open_kingsfords_pdf(self):
        from apps.communications.assistant import boss_tools
        m = self.sent('Typed_Table_A3_Landscape_.pdf', 'application/pdf', self.table_pdf())
        chat = boss_tools.read_chat(self.chat.pk)
        self.assertEqual(chat['messages'][-1]['file_id'], m.pk)
        found = boss_tools.open_file(m.pk)
        self.assertIn('1983', found['text'])
        self.assertEqual(found['what'], 'PDF, 1 page')

    def test_a_word_file(self):
        import io
        import zipfile
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w') as z:
            z.writestr('word/document.xml', '<w:document><w:body><w:p><w:r><w:t>Dear Sir &amp; Madam</w:t></w:r>'
                                            '</w:p><w:p><w:r><w:t>SIM request</w:t></w:r></w:p></w:body></w:document>')
        m = self.sent('letter.docx', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                      out.getvalue())
        from apps.communications.services import file_reader
        self.assertEqual(file_reader.read(m)['text'], 'Dear Sir & Madam\nSIM request')

    def test_what_cant_be_opened_is_said_plainly(self):
        from apps.communications.services import file_reader
        m = self.sent('design.cdr', 'application/octet-stream', b'xx')
        self.assertIn("can't open this kind of file", file_reader.read(m)['error'])

    def test_a_photo_is_shown_to_octos_as_a_picture(self):
        import io
        from PIL import Image
        from apps.communications.assistant import boss
        from apps.communications.tests_owner_boss import FakeModel, looks, said, turn
        buf = io.BytesIO()
        Image.new('RGB', (3000, 2000), 'white').save(buf, 'JPEG')
        m = self.sent('proof.jpg', 'image/jpeg', buf.getvalue(), mtype=Message.IMAGE)
        model = FakeModel(turn(looks('open_file', file_id=m.pk)), turn(said('A plain white page, boss.')))
        calls, usage = [], {'input': 0, 'output': 0, 'cache_read': 0}
        with patch('anthropic.Anthropic', return_value=model), patch.object(boss, '_say'), \
                patch.object(boss, '_typing', create=True):
            reply = boss._converse([{'role': 'user', 'content': 'What did Amoree send?'}], calls, [], usage,
                                   None, timezone.now())
        self.assertEqual(reply, 'A plain white page, boss.')
        result = model.calls[1]['messages'][-1]['content'][0]['content']
        self.assertEqual(result[1]['type'], 'image')
        self.assertEqual(result[1]['source']['media_type'], 'image/jpeg')
        self.assertNotIn('_image', calls[-1]['result'])                  # never kept as text for the checker

    def test_the_rules_say_open_it_before_saying_you_cant(self):
        from apps.communications.assistant import boss
        self.assertIn("never tell him you can't read a file you haven't tried", boss.RULES)


class VoiceNoteTests(TestCase):

    def setUp(self):
        make_org('-VN')
        self.chat = make_conversation(None, contact_phone='+233244771060')

    def step(self, message):
        with patch('apps.communications.services.opened.in_focus', return_value=False), \
                patch('apps.communications.assistant.counter.shop_open', return_value=True):
            return counter.step(self.chat, message, timezone.now())

    def test_asked_to_type_it_once_a_visit(self):
        voice = inbound(self.chat, message_type=Message.AUDIO, media_id='m-v1')
        said, why = self.step(voice)
        self.assertEqual(said, counter.VOICE_TEXT)
        self.assertIn('Could you type it', said)
        AssistantRun.objects.create(conversation=self.chat, trigger=voice, reason=why, mode='live')
        again = inbound(self.chat, message_type=Message.AUDIO, media_id='m-v2')
        self.assertEqual(self.step(again), (None, 'voice note: asked them to type already'))

    def test_a_person_with_the_chat_open_has_it(self):
        voice = inbound(self.chat, message_type=Message.AUDIO, media_id='m-v3')
        with patch('apps.communications.services.opened.in_focus', return_value=True), \
                patch('apps.communications.assistant.counter.shop_open', return_value=True):
            self.assertEqual(counter.step(self.chat, voice, timezone.now()), (None, 'a person has this chat open'))


class RegularTests(TestCase):

    def setUp(self):
        self.branch = make_org('-RG')
        self.branch.name = 'Westland Branch'
        self.branch.save()
        self.customer = CustomerProfile.objects.create(first_name='Akos', phone='+233244771070',
                                                       customer_type='INDIVIDUAL')
        self.chat = make_conversation(None, contact_phone='+233244771070', customer=self.customer)

    def earlier_job(self, days=10):
        job = Job.objects.create(branch=self.branch, status='PAID', customer=self.customer, title='CV printing',
                                 job_type=Job.INSTANT)
        Job.objects.filter(pk=job.pk).update(created_at=timezone.now() - timedelta(days=days))
        return job

    def test_someone_new_gets_the_plain_welcome(self):
        self.assertEqual(counter.ack_text(self.chat, self.branch),
                         "Hi Akos 👋 Welcome to Farhat Westland. Hand your files to the attendant, "
                         "or drop them here and they'll pick them up.")

    def test_a_regular_is_welcomed_back_and_never_the_same_words_twice(self):
        self.earlier_job()
        seen = []
        for _ in range(4):
            text = counter.ack_text(self.chat, self.branch)
            self.assertIn('Akos', text)
            self.assertNotIn('Welcome to Farhat Westland.', text)
            seen.append(text)
            AssistantRun.objects.create(conversation=self.chat, reason=counter.ACK_REASON, mode='live', reply=text)
        self.assertTrue(seen[0].startswith('Welcome back, Akos'))
        self.assertTrue(all(a != b for a, b in zip(seen, seen[1:])))

    def test_octos_knows_their_history_and_speaks_like_he_knows_them(self):
        self.earlier_job()
        line = prompt._customer_line(self.chat)
        self.assertIn('They have had 1 job with us', line)
        self.assertIn('open like someone who remembers them', line)

    def test_todays_work_is_in_view(self):
        job = Job.objects.create(branch=self.branch, status='PAID', customer=self.customer, title='Portfolio',
                                 job_type=Job.INSTANT)
        line = prompt._customer_line(self.chat)
        self.assertIn(f'Made for them today: {job.job_number}', line)
        self.assertIn('Never ask what to do with files for these', line)
        self.assertNotIn('open like someone who remembers them', line)       # first job ever: not a regular yet


class SofterTests(SimpleTestCase):

    def verdict(self, *names_):
        return {'verdict': 'warn', 'checks': [{'name': n, 'verdict': 'warn', 'message': 'x'} for n in names_]}

    def service(self, name='A4 Colour Printing (one side)', unit='PER_PIECE'):
        return SimpleNamespace(name=name, display_name='', code='A4-COL-1S', unit=unit)

    def test_a_letter_on_a4_is_not_warned(self):
        pdf_file = SimpleNamespace(media_mime='application/pdf')
        self.assertFalse(ordering._worth_a_warning(self.verdict('resolution'), self.service(), pdf_file))

    def test_photos_and_big_prints_still_are(self):
        photo = SimpleNamespace(media_mime='image/jpeg')
        pdf_file = SimpleNamespace(media_mime='application/pdf')
        self.assertTrue(ordering._worth_a_warning(self.verdict('resolution'), self.service(), photo))
        self.assertTrue(ordering._worth_a_warning(self.verdict('resolution'), self.service('Banner', 'PER_SQFT'),
                                                  pdf_file))
        self.assertTrue(ordering._worth_a_warning(self.verdict('resolution'), self.service('A3 Poster'), pdf_file))

    def test_other_warnings_always_stand(self):
        pdf_file = SimpleNamespace(media_mime='application/pdf')
        self.assertTrue(ordering._worth_a_warning(self.verdict('pages'), self.service(), pdf_file))

    def test_the_price_comes_first(self):
        self.assertIn('give the price (from quote) first', prompt.RULES)
        self.assertIn('never open with the warning', prompt.RULES)
