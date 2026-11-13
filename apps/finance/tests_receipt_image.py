"""
The WhatsApp receipt picture (13 Nov 2026): drawn from plain data, no database.
"""
from io import BytesIO

from django.test import SimpleTestCase
from PIL import Image

from apps.finance.services.receipt_image import render


def data(items):
    return {
        'branch': 'Westland Branch', 'branch_phone': '055 196 9777', 'first_name': 'Faustina',
        'receipt_number': 'RCP-WLB-2026-05893', 'amount_paid': '27.00', 'when': '13 NOV 2026 | 11:33',
        'job_number': 'FP-WLB-2026-05939', 'method': 'MOMO', 'method_label': 'Mobile Money',
        'method_note': 'Ref 12345678901 · received by Ama Mensah', 'items': items,
        'total': '27.00', 'balance': '0.00',
    }


ONE = {'number': 1, 'name': 'A4 Colour Printing', 'count': '6 pages', 'tags': ['Colour', 'One side'],
       'sum': '6 pages × GHS 2.50', 'amount': '15.00', 'is_addon': False}


class ReceiptImageTests(SimpleTestCase):
    def test_it_is_a_png(self):
        png = render(data([ONE]))
        self.assertTrue(png.startswith(b'\x89PNG'))
        self.assertEqual(Image.open(BytesIO(png)).format, 'PNG')

    def test_the_picture_grows_with_the_order(self):
        short = Image.open(BytesIO(render(data([ONE])))).height
        long = Image.open(BytesIO(render(data([ONE] * 6)))).height
        self.assertGreater(long, short)

    def test_a_walk_in_and_an_unknown_method_still_draw(self):
        d = data([ONE])
        d.update(first_name='', method='SOMETHING_NEW', method_label='Something new', method_note='')
        self.assertTrue(render(d).startswith(b'\x89PNG'))
