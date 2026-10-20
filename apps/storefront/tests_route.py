"""Directions: asked of OpenRouteService with the server's key, trimmed, remembered."""

import os
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

URL = '/api/v1/storefront/route/'
ORS_ANSWER = {'features': [{
    'geometry': {'coordinates': [[-0.10, 5.60], [-0.11, 5.61], [-0.12, 5.62]]},
    'properties': {
        'summary': {'distance': 4200.4, 'duration': 900.2},
        'segments': [{'steps': [
            {'instruction': 'Head north', 'name': '-', 'type': 11, 'distance': 300, 'way_points': [0, 1]},
            {'instruction': 'Turn right onto Spintex Road', 'name': 'Spintex Road', 'type': 1,
             'distance': 3900, 'way_points': [1, 2]},
        ]}],
    },
}]}


class RouteTests(TestCase):

    def setUp(self):
        cache.clear()

    def _get(self, **params):
        query = {'from': '5.60,-0.10', 'to': '5.62,-0.12', 'mode': 'driving', **params}
        return APIClient().get(URL, query)

    def test_without_a_key_it_says_so(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('ORS_API_KEY', None)
            self.assertEqual(self._get().status_code, 503)

    def test_bad_points_are_refused(self):
        self.assertEqual(self._get(**{'from': 'nowhere'}).status_code, 400)
        self.assertEqual(self._get(mode='flying').status_code, 400)

    @patch.dict(os.environ, {'ORS_API_KEY': 'test-key'})
    def test_the_route_comes_back_trimmed_to_what_the_screen_draws(self):
        with patch('apps.storefront.route_views.requests.post',
                   return_value=MagicMock(status_code=200, json=lambda: ORS_ANSWER)) as post:
            data = self._get().json()
        self.assertEqual(post.call_args.kwargs['headers']['Authorization'], 'test-key')
        self.assertEqual(data['distance_m'], 4200)
        self.assertEqual(data['duration_s'], 900)
        self.assertEqual(data['path'][0], [5.60, -0.10])
        self.assertEqual(data['steps'][1]['name'], 'Spintex Road')
        self.assertEqual(data['steps'][0]['name'], '')
        self.assertEqual(data['steps'][1]['at'], [5.61, -0.11])

    @patch.dict(os.environ, {'ORS_API_KEY': 'test-key'})
    def test_the_same_route_is_asked_for_once(self):
        with patch('apps.storefront.route_views.requests.post',
                   return_value=MagicMock(status_code=200, json=lambda: ORS_ANSWER)) as post:
            self._get()
            self._get()
        self.assertEqual(post.call_count, 1)