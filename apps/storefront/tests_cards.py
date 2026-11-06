"""
The payment card: drawn from a real order, a PNG, and long details wrap
instead of breaking the layout.
"""
import io
from decimal import Decimal

from django.test import TestCase
from PIL import Image

from apps.storefront.models import Lead, OnlineOrder
from apps.storefront.services.cards import paid_card


class PaidCardTests(TestCase):

    def order(self, first_name='James'):
        lead = Lead.objects.create(phone='+233244000222', first_name=first_name)
        return OnlineOrder.objects.create(lead=lead, total=Decimal('50.00'), full_total=Decimal('50.00'))

    def test_a_paid_order_draws_a_png_card(self):
        png = paid_card(self.order())
        self.assertTrue(png.startswith(b'\x89PNG'))
        image = Image.open(io.BytesIO(png))
        self.assertEqual(image.width, 1632)

    def test_long_details_wrap_and_the_card_grows(self):
        short = Image.open(io.BytesIO(paid_card(self.order())))
        OnlineOrder.objects.all().delete()
        Lead.objects.all().delete()
        long = Image.open(io.BytesIO(paid_card(self.order(first_name='Bartholomew-Kwabena'))))
        self.assertEqual(long.width, short.width)