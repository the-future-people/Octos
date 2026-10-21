"""The counter's promise: the prediction service's answer, at the attendant's branch."""

from datetime import datetime, timezone as dt_timezone
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from apps.jobs.tests import JobsFixtureMixin

URL = '/api/v1/jobs/promise/'


class CounterPromiseTests(JobsFixtureMixin, TestCase):

    def _client(self):
        client = APIClient()
        client.force_authenticate(self.bm)
        return client

    def test_the_promise_comes_from_the_prediction_service(self):
        service = self.services[0] if hasattr(self, 'services') else None
        from apps.jobs.models import Service
        service = service or Service.objects.filter(is_active=True).first()
        when = datetime(2026, 10, 21, 15, 40, tzinfo=dt_timezone.utc)
        with patch('apps.production.services.prediction_service.PredictionService.predict',
                   return_value=SimpleNamespace(ready_at=when)) as predict:
            data = self._client().post(URL, {'lines': [{'service': service.pk, 'quantity': 2, 'pages': 3}]},
                                       format='json').json()
        self.assertEqual(data['ready_at'], when.isoformat())
        sent = predict.call_args[0][0]
        self.assertEqual(sent[0][1:], (2, 3))

    def test_an_empty_cart_is_refused(self):
        self.assertEqual(self._client().post(URL, {'lines': []}, format='json').status_code, 400)

    def test_when_octos_cannot_say_it_says_so(self):
        from apps.jobs.models import Service
        service = Service.objects.filter(is_active=True).first()
        with patch('apps.production.services.prediction_service.PredictionService.predict',
                   side_effect=RuntimeError('no calendar')):
            data = self._client().post(URL, {'lines': [{'service': service.pk}]}, format='json').json()
        self.assertIsNone(data['ready_at'])
        self.assertIn('coordinator', data['detail'])

    def test_the_counter_needs_staff(self):
        self.assertEqual(APIClient().post(URL, {'lines': [{'service': 1}]}, format='json').status_code, 401)