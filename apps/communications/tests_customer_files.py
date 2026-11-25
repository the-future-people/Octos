"""
Customer files: kept 14 days, Keep when they ask, deleted on request with a
record that stays (25 Nov 2026).

Run: docker compose run --rm web python manage.py test apps.communications.tests_customer_files -t .
"""
import hashlib
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.communications.assistant import brain, prompt
from apps.communications.models import Message
from apps.communications.services import customer_files
from apps.communications.services.customer_files import FilesRefused
from apps.communications.tests import make_conversation
from apps.jobs.models import Job, JobFile
from apps.jobs.tests_front_desk import Base
from apps.spine import kinds
from apps.spine.models import Event
from apps.storefront.models import Lead, OnlineOrder, OrderFile

CV = b'%PDF-1.4 Ama Mensah CV'
SLIP = b'\x89PNG results slip'


@override_settings(FILE_CLEANUP_STARTS='2026-01-01')
class FilesBase(Base):

    def setUp(self):
        super().setUp()
        self.chat = make_conversation(None, contact_phone='+233244000731', contact_name='Ama')
        for p in (patch('apps.communications.services.owner_line.tell'),
                  patch('apps.communications.services.whatsapp_outbound.send_text'),
                  patch('apps.communications.services.window.window_open', return_value=True)):
            p.start()
            self.addCleanup(p.stop)

    def sent(self, content, name='Ama Mensah CV.pdf', ago=None, **fields):
        m = Message.objects.create(conversation=self.chat, direction=fields.pop('direction', Message.INBOUND),
                                   channel=Message.WHATSAPP, message_type=Message.DOCUMENT,
                                   media_name=name, media_pages=2, media_size=len(content), **fields)
        m.media_file.save(name, ContentFile(content), save=True)
        if ago:
            Message.objects.filter(pk=m.pk).update(created_at=timezone.now() - ago)
            m.refresh_from_db()
        return m

    def job(self, done=True, content=None):
        job = Job.objects.create(
            branch=self.branch, job_type=Job.INSTANT, title='Printing', estimated_cost=Decimal('10'),
            status=Job.COMPLETE if done else Job.PENDING_PAYMENT,
            payment_state=Job.Payment.SETTLED if done else Job.Payment.UNPAID,
            handover_state=Job.Handover.HANDED_OVER if done else Job.Handover.AWAITING_COLLECTION)
        self.chat.jobs.add(job)
        if content is not None:
            f = JobFile(job=job)
            f.file.save('copy.pdf', ContentFile(content), save=True)
        return job


class WhichFilesTests(FilesBase):

    def test_theirs_and_what_staff_sent_them_but_not_our_own(self):
        theirs = self.sent(CV)
        artwork = self.sent(b'artwork', 'Untitled-265.jpg', direction=Message.OUTBOUND, sent_by=self.esi)
        self.sent(b'receipt', 'RCP.png', direction=Message.OUTBOUND, kind='receipt')
        self.sent(b'preview', 'preview.png', direction=Message.OUTBOUND)              # Octos's own
        self.assertEqual(list(customer_files.chat_files(self.chat)), [theirs, artwork])

    def test_the_day_it_goes_and_none_once_kept(self):
        m = self.sent(CV)
        self.assertEqual(customer_files.deletes_on(m), timezone.localdate(m.created_at) + timedelta(days=15))
        customer_files.keep([m], self.esi)
        m.refresh_from_db()
        self.assertIsNone(customer_files.deletes_on(m))


class KeepTests(FilesBase):

    def test_keep_and_give_it_back_its_days(self):
        m = self.sent(CV)
        self.assertEqual(customer_files.keep([m], self.esi), 1)
        m.refresh_from_db()
        self.assertEqual(m.kept_by, self.esi)
        self.assertTrue(Event.objects.filter(kind=kinds.FILE_KEPT, conversation=self.chat).exists())
        customer_files.keep([m], self.esi, keep_it=False)
        m.refresh_from_db()
        self.assertIsNone(m.kept_at)

    def test_octos_keeps_the_chat_at_the_customer_s_word(self):
        a = self.sent(CV)
        self.sent(SLIP, 'Results slip.jpg')
        self.assertEqual(customer_files.keep_chat(self.chat), 2)
        a.refresh_from_db()
        self.assertIsNotNone(a.kept_at)
        self.assertIsNone(a.kept_by)
        self.assertIn('keep_files', {t['name'] for t in brain.TOOL_SPECS})


class DeleteByHandTests(FilesBase):

    def test_an_attendant_deletes_with_a_reason_and_the_record_stays(self):
        m = self.sent(CV)
        stored = m.media_file.name
        storage = m.media_file.storage
        with self.captureOnCommitCallbacks(execute=True):
            done = customer_files.delete_by_hand(self.chat, [m.pk], self.esi, 'asked')
        self.assertEqual(done, [m])
        m.refresh_from_db()
        self.assertFalse(m.media_file)
        self.assertFalse(storage.exists(stored))
        self.assertEqual((m.file_deleted_by, m.file_delete_reason), (self.esi, 'The customer asked'))
        self.assertEqual(m.file_sha256, hashlib.sha256(CV).hexdigest())
        self.assertEqual((m.media_name, m.media_pages), ('Ama Mensah CV.pdf', 2))       # the record stays
        event = Event.objects.get(kind=kinds.FILE_DELETED, conversation=self.chat)
        self.assertEqual(event.payload['sha256'], m.file_sha256)
        from apps.communications.services import owner_line
        owner_line.tell.assert_called_once()
        self.assertIn('Ama Mensah CV.pdf', owner_line.tell.call_args.args[1])
        from apps.communications.services import whatsapp_outbound
        whatsapp_outbound.send_text.assert_called_once()

    def test_copies_on_their_jobs_and_orders_go_too_and_other_files_stay(self):
        m = self.sent(CV)
        self.job(done=True, content=CV)
        other = self.job(done=True, content=b'something else')
        lead = Lead.objects.create(phone='+233244000731', first_name='Ama')
        order = OnlineOrder.objects.create(lead=lead, branch=self.branch, total=Decimal('5'),
                                           notes=f'Taken by Octos on WhatsApp (conversation {self.chat.pk})')
        of = OrderFile(order=order, original_filename='cv.pdf')
        of.file.save('cv.pdf', ContentFile(CV), save=True)
        customer_files.delete_by_hand(self.chat, [m.pk], self.esi, 'mistake')
        self.assertEqual(JobFile.objects.filter(job__conversations=self.chat).count(), 1)
        self.assertTrue(JobFile.objects.filter(job=other).exists())
        self.assertFalse(OrderFile.objects.filter(pk=of.pk).exists())
        copies = Event.objects.get(kind=kinds.FILE_DELETED).payload['copies']
        self.assertEqual({c['what'] for c in copies}, {'job file', 'order file'})

    def test_the_customer_is_told_only_when_they_asked(self):
        m = self.sent(CV)
        with self.captureOnCommitCallbacks(execute=True):
            customer_files.delete_by_hand(self.chat, [m.pk], self.esi, 'mistake')
        from apps.communications.services import whatsapp_outbound
        whatsapp_outbound.send_text.assert_not_called()

    def test_a_cashier_cannot_delete(self):
        m = self.sent(CV)
        with self.assertRaises(FilesRefused):
            customer_files.delete_by_hand(self.chat, [m.pk], self.cashier, 'asked')


class LockTests(FilesBase):

    def test_an_open_job_locks_them_for_an_attendant(self):
        m = self.sent(CV)
        job = self.job(done=False)
        self.assertEqual(customer_files.lock_text(customer_files.open_job(self.chat)),
                         f'On job {job.job_number}, not paid yet')
        with self.assertRaisesMessage(FilesRefused, 'Locked for now'):
            customer_files.delete_by_hand(self.chat, [m.pk], self.esi, 'asked')
        m.refresh_from_db()
        self.assertTrue(m.media_file)

    def test_the_bm_may_lift_the_lock(self):
        m = self.sent(CV)
        self.job(done=False)
        self.assertEqual(len(customer_files.delete_by_hand(self.chat, [m.pk], self.manager, 'asked')), 1)

    def test_paid_and_collected_unlocks_it(self):
        self.sent(CV)
        self.job(done=True)
        self.assertIsNone(customer_files.open_job(self.chat))

    def test_the_owner_lets_them_from_his_line(self):
        m = self.sent(CV)
        self.job(done=False)
        from apps.communications.services import owner_line
        owner_line.tell.return_value = object()
        customer_files.ask_owner(self.chat, [m.pk], self.esi, 'asked', 'sending a new version')
        buttons = owner_line.tell.call_args.kwargs['buttons']
        self.assertEqual([b['title'] for b in buttons], ['Let them delete it', 'Keep it'])
        self.assertIsNone(customer_files.tap(buttons[1]['id']))
        m.refresh_from_db()
        self.assertTrue(m.media_file)
        customer_files.tap(buttons[0]['id'])
        m.refresh_from_db()
        self.assertFalse(m.media_file)
        self.assertEqual(m.file_deleted_by, self.esi)
        self.assertIn('allowed by Khofi', m.file_delete_reason)

    def test_the_owner_line_routes_the_tap(self):
        from apps.communications.models import OwnerMessage
        from apps.communications.services import owner_line
        tap = OwnerMessage.objects.create(direction=OwnerMessage.IN, kind='reply', body='Keep it',
                                          reply_id='files:keep:1:2:asked:3')
        with patch('apps.communications.services.customer_files.tap') as tapped, \
                patch('apps.communications.services.owner_line.flush', return_value=0):
            owner_line.answer(tap.pk)
        tapped.assert_called_once_with('files:keep:1:2:asked:3')


class CleanTests(FilesBase):

    def test_older_than_fourteen_days_goes_unless_kept_or_held(self):
        old = self.sent(CV, ago=timedelta(days=15))
        kept = self.sent(SLIP, 'Results slip.jpg', ago=timedelta(days=20))
        customer_files.keep([kept], self.esi)
        young = self.sent(b'young', 'young.pdf', ago=timedelta(days=10))
        self.assertEqual(customer_files.clean(), 1)
        old.refresh_from_db()
        kept.refresh_from_db()
        young.refresh_from_db()
        self.assertFalse(old.media_file)
        self.assertEqual(old.file_delete_reason, customer_files.OCTOS_REASON)
        self.assertIsNone(old.file_deleted_by)
        self.assertTrue(kept.media_file)
        self.assertTrue(young.media_file)
        self.assertEqual(customer_files.cleared_since(timezone.now() - timedelta(minutes=1)), 1)

    def test_an_open_job_keeps_them_until_it_is_done(self):
        old = self.sent(CV, ago=timedelta(days=15))
        job = self.job(done=False)
        self.assertEqual(customer_files.clean(), 0)
        Job.objects.filter(pk=job.pk).update(payment_state=Job.Payment.SETTLED,
                                             handover_state=Job.Handover.HANDED_OVER)
        self.assertEqual(customer_files.clean(), 1)
        old.refresh_from_db()
        self.assertFalse(old.media_file)

    def test_old_job_files_go_but_not_a_copy_of_a_kept_file(self):
        kept = self.sent(CV)
        customer_files.keep([kept], self.esi)
        customer_files._message_print(kept)
        self.job(done=True, content=CV)
        other = self.job(done=True, content=b'old artwork')
        JobFile.objects.update(created_at=timezone.now() - timedelta(days=15))
        self.assertEqual(customer_files.clean(), 1)
        self.assertFalse(JobFile.objects.filter(job=other).exists())
        self.assertEqual(JobFile.objects.count(), 1)

    @override_settings(FILE_CLEANUP_STARTS='2999-01-01')
    def test_nothing_before_the_start_date(self):
        self.sent(CV, ago=timedelta(days=30))
        self.assertEqual(customer_files.clean(), 0)


class ApiTests(FilesBase):

    def api(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def test_list_keep_and_delete(self):
        m = self.sent(CV)
        with patch('apps.communications.api.views._visible', return_value=self.chat):
            data = self.api(self.esi).get(f'/api/v1/communications/{self.chat.pk}/files/').json()
            self.assertEqual([f['id'] for f in data['files']], [m.pk])
            self.assertEqual((data['locked'], data['may_delete'], data['may_unlock']), ('', True, False))
            kept = self.api(self.esi).post(f'/api/v1/communications/messages/{m.pk}/keep/', {'keep': True}, format='json')
            self.assertTrue(kept.json()['kept'])
            no_reason = self.api(self.esi).post(f'/api/v1/communications/{self.chat.pk}/files/delete/',
                                                {'ids': [m.pk]}, format='json')
            self.assertEqual(no_reason.status_code, 400)
            gone = self.api(self.esi).post(f'/api/v1/communications/{self.chat.pk}/files/delete/',
                                           {'ids': [m.pk], 'reason': 'asked'}, format='json')
            self.assertEqual(gone.json()['deleted'], [m.pk])

    def test_the_chat_shows_kept_and_deleted(self):
        from apps.communications.api.serializers import MessageSerializer
        m = self.sent(CV)
        self.assertIn('deletes_on', MessageSerializer(m).data['file_keep'])
        customer_files.delete(self.chat, [m], self.esi, 'asked')
        m.refresh_from_db()
        record = MessageSerializer(m).data['file_keep']['deleted']
        self.assertEqual((record['by'], record['reason']), ('Esi', 'The customer asked'))


class OctosWordsTests(FilesBase):

    def test_octos_knows_the_fourteen_days_and_keep(self):
        self.assertIn('We keep the files customers send us for 14 days', prompt.RULES)
        self.assertIn('call keep_files', prompt.RULES)
