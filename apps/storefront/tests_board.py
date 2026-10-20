"""The waiting-area board: switched on by a key, short numbers only."""

import os
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

URL = '/api/v1/storefront/board/WLB/'


class BoardTests(TestCase):

    def test_without_a_key_set_the_board_is_off(self):
        with patch.dict(os.environ, {'BOARD_KEY': ''}):
            self.assertEqual(APIClient().get(URL).status_code, 503)

    @patch.dict(os.environ, {'BOARD_KEY': 'shop-tv'})
    def test_the_wrong_key_is_refused(self):
        self.assertEqual(APIClient().get(URL, {'key': 'guess'}).status_code, 403)

    @patch.dict(os.environ, {'BOARD_KEY': 'shop-tv'})
    def test_the_right_key_shows_the_board_and_nothing_personal(self):
        data = APIClient().get(URL, {'key': 'shop-tv'}).json()
        self.assertEqual(set(data), {'branch', 'now', 'making', 'ready'})
        self.assertEqual(data['branch'], 'WLB')