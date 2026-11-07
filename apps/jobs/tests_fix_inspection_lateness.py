"""
7 Nov 2026: passport photos judged at their own size, shapes that can be
fitted rather than only held, and lateness that never spams a customer.
"""
from datetime import timedelta
from types import SimpleNamespace

from django.test import SimpleTestCase
from django.utils import timezone

from apps.jobs.services import intake_check, lateness


class InspectionTests(SimpleTestCase):

    def test_a_passport_photo_has_its_own_size(self):
        line = SimpleNamespace(service=SimpleNamespace(code='PP-US'), specifications={}, paper_size='A4')
        short, long_, label = intake_check.ordered_size(line)
        self.assertEqual((short, long_), (50.8, 50.8))
        self.assertIn('American passport', label)

    def test_a_passport_photo_needs_no_bleed(self):
        service = SimpleNamespace(name='Passport Photo (American)', unit='SET', code='PP-US')
        self.assertEqual(intake_check.rules_for(service)['bleed_mm'], 0)

    def test_documents_still_follow_their_paper(self):
        line = SimpleNamespace(service=SimpleNamespace(code='A4-COL-PRINT-1S'), specifications={}, paper_size='A4')
        self.assertEqual(intake_check.ordered_size(line)[2], 'A4')


class LatenessTests(SimpleTestCase):

    def setUp(self):
        self.now = timezone.now()

    def test_turning_late_does_not_skip_the_two_hour_gap(self):
        d = lateness.decide(promise=self.now - timedelta(minutes=1), live=self.now + timedelta(minutes=30),
                            now=self.now, state=lateness.AT_RISK, last_told=self.now - timedelta(minutes=20))
        self.assertEqual(d.state, lateness.LATE)
        self.assertFalse(d.tell_customer)

    def test_the_customer_is_told_once_the_gap_has_passed(self):
        d = lateness.decide(promise=self.now - timedelta(minutes=1), live=self.now + timedelta(minutes=30),
                            now=self.now, state=lateness.LATE, last_told=self.now - timedelta(hours=3))
        self.assertTrue(d.tell_customer)

    def test_staff_hear_of_a_change_not_every_revision(self):
        d = lateness.decide(promise=self.now + timedelta(minutes=10), live=self.now + timedelta(minutes=40),
                            now=self.now, state=lateness.AT_RISK, last_told=None)
        self.assertEqual(d.state, lateness.AT_RISK)
        self.assertFalse(d.tell_staff)
