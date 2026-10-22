"""The batch commit refuses what it should before touching anything."""

from django.test import TestCase
from rest_framework.test import APIClient

URL = '/api/v1/storefront/commit/batch/'


class BatchCommitTests(TestCase):

    def _post(self, body):
        return APIClient().post(URL, body, format='json')

    def test_a_key_is_required(self):
        self.assertEqual(self._post({'files': [{}]}).status_code, 400)

    def test_files_are_required(self):
        r = self._post({'idempotency_key': 'k1', 'files': []})
        self.assertEqual(r.status_code, 400)
        self.assertIn('file', r.json()['detail'])

    def test_no_more_than_fifteen_files(self):
        r = self._post({'idempotency_key': 'k2', 'files': [{}] * 16})
        self.assertEqual(r.status_code, 400)
        self.assertIn('15', r.json()['detail'])

    def test_an_unknown_service_is_refused(self):
        r = self._post({'idempotency_key': 'k3', 'files': [{'checked_service': 999999, 'sets': [{}]}]})
        self.assertEqual(r.status_code, 400)