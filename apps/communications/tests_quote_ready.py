"""
A quote says when it could be ready, read from the floor (7 Nov 2026).
"""
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.communications.assistant import tools
from apps.communications.tests import make_org
from apps.jobs.models import PricingRule, Service

PREDICT = 'apps.production.services.prediction_service.PredictionService.predict'


class QuoteReadyTests(TestCase):

    def setUp(self):
        self.branch = make_org()
        self.branch.is_trading = True
        self.branch.save()
        self.flyers = Service.objects.create(code='FLY-A5', name='A5 Flyers', category='INSTANT',
                                             unit='PER_PIECE', is_active=True)
        PricingRule.objects.create(service=self.flyers, branch=None, base_price=Decimal('1.50'), is_active=True)

    def test_a_quote_carries_a_window_from_the_floor(self):
        ready_at = timezone.make_aware(datetime(2026, 11, 9, 17, 22))
        with patch(PREDICT, return_value=SimpleNamespace(ready_at=ready_at)), \
                patch('django.utils.timezone.now', return_value=timezone.make_aware(datetime(2026, 11, 9, 9, 0))):
            facts = tools.quote('FLY-A5', {}, 500)
        self.assertTrue(facts['success'])
        self.assertTrue(facts['ready'].startswith('between 5:30pm and 6:00pm today at '))

    def test_when_the_floor_cannot_say_no_time_is_given(self):
        with patch(PREDICT, return_value=SimpleNamespace(ready_at=None)):
            facts = tools.quote('FLY-A5', {}, 500)
        self.assertIsNone(facts['ready'])
        self.assertEqual(facts['ready_note'], 'The team will confirm the ready time.')

    def test_a_failure_reading_the_floor_never_breaks_the_price(self):
        with patch(PREDICT, side_effect=RuntimeError('floor unreadable')):
            facts = tools.quote('FLY-A5', {}, 500)
        self.assertTrue(facts['success'])
        self.assertIsNone(facts['ready'])
