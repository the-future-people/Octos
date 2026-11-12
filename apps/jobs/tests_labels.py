"""
One answer for who a job is for and who recorded it (12 Nov 2026).
"""
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.jobs.services import labels


def _job(**kw):
    base = dict(customer_id=None, customer=None, intake_by_id=None, intake_by=None, intake_channel='WALK_IN')
    base.update(kw)
    return SimpleNamespace(**base)


class LabelTests(SimpleTestCase):
    def test_a_registered_customer_is_named_by_their_record(self):
        job = _job(customer_id=1, customer=SimpleNamespace(display_name='Ama Owusu', phone='0244111222'))
        self.assertEqual(labels.for_whom(job), ('Ama Owusu', False))
        self.assertEqual(labels.contact_phone(job), '0244111222')

    @patch('apps.jobs.services.labels._chat', return_value=('Linc (WhatsApp @linc_gh)', ''))
    def test_an_unregistered_chat_customer_is_named_by_the_chat(self, _chat):
        self.assertEqual(labels.for_whom(_job()), ('Linc (WhatsApp @linc_gh)', True))

    @patch('apps.jobs.services.labels._chat', return_value=('Ama (WhatsApp)', '+233244111226'))
    def test_the_chats_number_is_the_contact_when_there_is_no_record(self, _chat):
        self.assertEqual(labels.contact_phone(_job()), '+233244111226')

    @patch('apps.jobs.services.labels._chat', return_value=None)
    def test_no_record_and_no_chat_is_a_walk_in(self, _chat):
        self.assertEqual(labels.for_whom(_job()), ('Walk-in', False))
        self.assertEqual(labels.contact_phone(_job()), '')

    def test_recorded_by_the_attendant_else_the_channel(self):
        self.assertEqual(labels.recorded_by(_job(intake_by_id=3, intake_by=SimpleNamespace(full_name='Ama Mensah'))), 'Ama Mensah')
        self.assertEqual(labels.recorded_by(_job(intake_channel='ONLINE')), 'Print Octos (online)')
        self.assertEqual(labels.recorded_by(_job()), '—')
