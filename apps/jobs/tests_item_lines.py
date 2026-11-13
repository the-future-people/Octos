"""
One way of describing items, for the modal and both receipts (13 Nov 2026).
"""
from types import SimpleNamespace as NS

from django.test import SimpleTestCase

from apps.jobs.services.item_lines import describe, describe_job, thermal, whatsapp

PAGES = {'pages': {}}


def item(pk, name, *, pages=1, sets=1, qty=1, colour=False, sides='SINGLE', size='A4', unit='0', total='0',
         specs=None, parent=None, template=None):
    return NS(pk=pk, parent_id=parent, pages=pages, sets=sets, quantity=qty, is_color=colour, sides=sides,
              paper_size=size, unit_price=unit, line_total=total, specifications=specs or {},
              service=NS(name=name, spec_template=template if template is not None else {}))


class ItemLineTests(SimpleTestCase):
    def test_copies_are_sets_and_the_sum_adds_up(self):
        d = describe(item(1, 'A4 Colour Printing (one side)', pages=13, sets=2, colour=True, unit='2.00', total='52.00',
                          template=PAGES), 2)
        self.assertEqual(d['name'], 'A4 Colour Printing')
        self.assertEqual(d['count'], '13 pages × 2 copies')
        self.assertEqual(d['tags'], ['Colour', 'One side'])   # always, even when the name says colour
        self.assertEqual(d['sum'], '13 pages × 2 copies × GHS 2.00')

    def test_colour_is_a_tag_when_the_name_does_not_say_it(self):
        d = describe(item(1, 'Printing', pages=4, colour=True, unit='2.00', total='8.00', template=PAGES))
        self.assertEqual(d['name'], 'A4 Printing')
        self.assertEqual(d['tags'], ['Colour', 'One side'])

    def test_a_sum_that_does_not_add_up_is_never_shown(self):
        d = describe(item(1, 'A4 Photocopy', pages=11, unit='1.00', total='10.00', template=PAGES))
        self.assertEqual(d['sum'], '')
        self.assertEqual(d['count'], '11 pages')

    def test_pieces_get_no_colour_sides_or_default_paper_size(self):
        d = describe(item(1, 'Brown Envelope', qty=3, unit='0.50', total='1.50', specs={'size': 'A4'}))
        self.assertEqual(d['name'], 'Brown Envelope')
        self.assertEqual(d['count'], '3')
        self.assertEqual(d['tags'], ['A4'])
        self.assertEqual(d['sum'], '3 × GHS 0.50')

    def test_add_ons_sit_under_their_item_without_a_number(self):
        rows = describe_job([
            item(1, 'A4 Printing', pages=13, unit='1.00', total='13.00', template=PAGES),
            item(2, 'Spiral Binding', unit='10.00', total='10.00', parent=1),
            item(3, 'Brown Envelope', qty=2, unit='0.50', total='1.00'),
        ])
        self.assertEqual([(r['number'], r['is_addon']) for r in rows], [(1, False), (None, True), (2, False)])

    def test_the_receipt_is_numbered_and_fits_the_paper(self):
        lines = thermal([
            item(1, 'A4 Colour Printing (one side)', pages=13, sets=2, colour=True, unit='2.00', total='52.00', template=PAGES),
            item(2, 'Lamination', qty=12, unit='3.00', total='36.00', size='A3', specs={'finish': 'gloss'}),
        ], 40)
        self.assertEqual(lines[0], '2 items')
        # The modal's order: the item and amount, its breakdown, its choices.
        self.assertEqual(lines[2], '1. A4 Colour Printing'.ljust(35) + '52.00')
        self.assertEqual(lines[3], '   13 pages x 2 copies x 2.00')
        self.assertEqual(lines[4], '   Colour, one side')
        self.assertTrue(all(len(l) <= 40 for l in lines))
        self.assertTrue(all('×' not in l and '·' not in l for l in lines))

    def test_an_add_on_name_wraps_whole_words(self):
        lines = thermal([
            item(1, 'A4 Colour Printing', pages=6, colour=True, unit='2.50', total='15.00', template=PAGES),
            item(9, 'Brown Envelope (packed with your order)', unit='2.00', total='2.00', parent=1),
        ], 40)
        self.assertEqual(lines[5], '   + Brown Envelope (packed with'.ljust(36) + '2.00')
        self.assertEqual(lines[6], '     your order)')

    def test_whatsapp_lists_the_same_items(self):
        out = whatsapp([item(1, 'A4 Photocopy', pages=11, unit='1.00', total='11.00', template=PAGES)])
        self.assertEqual(out[0], '  1. A4 Photocopy · B&W, One side — GHS 11.00')
        self.assertEqual(out[1], '     11 pages × GHS 1.00')

    def test_a_long_name_keeps_its_amount(self):
        lines = thermal([item(1, 'Black and White Laser Printing Extra Large Format', pages=3, unit='1.00', total='3.00',
                              template=PAGES, specs={'finish': 'stapled corner'})], 40)
        self.assertTrue(lines[2].endswith('3.00'))
        self.assertEqual(len(lines[2]), 40)
        # Wrapped by whole words, nothing cut: every word of the name is printed.
        printed = ' '.join(l.strip() for l in lines[2:4]).replace('3.00', '')
        for word in 'Black and White Laser Printing Extra Large Format'.split():
            self.assertIn(word, printed)
        self.assertEqual(lines[-1], '   B&W, one side, Stapled corner')
