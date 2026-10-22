"""Page sets: read the customer's selection, refuse what does not fit the file."""

from django.test import SimpleTestCase

from apps.storefront.services.page_sets import SelectionRefused, format_selection, parse_selection


class ParseTests(SimpleTestCase):

    def test_pages_and_ranges(self):
        self.assertEqual(parse_selection('1, 5, 8-10', 12), [1, 5, 8, 9, 10])

    def test_en_dashes_and_spaces_and_repeats(self):
        self.assertEqual(parse_selection(' 3 – 4 , 4, 1 ', 12), [1, 3, 4])

    def test_all_or_nothing_typed_means_every_page(self):
        self.assertEqual(parse_selection('all', 3), [1, 2, 3])
        self.assertEqual(parse_selection('', 3), [1, 2, 3])

    def test_a_page_past_the_end_is_refused(self):
        with self.assertRaises(SelectionRefused) as refused:
            parse_selection('1, 14', 12)
        self.assertIn('12 pages', str(refused.exception))

    def test_words_are_refused(self):
        with self.assertRaises(SelectionRefused):
            parse_selection('first page', 12)

    def test_page_zero_is_refused(self):
        with self.assertRaises(SelectionRefused):
            parse_selection('0-2', 12)

    def test_a_backwards_range_is_read_forwards(self):
        self.assertEqual(parse_selection('5-3', 12), [3, 4, 5])


class FormatTests(SimpleTestCase):

    def test_runs_read_as_ranges(self):
        self.assertEqual(format_selection([1, 2, 3, 5, 8, 9]), '1–3, 5, 8–9')

    def test_one_page(self):
        self.assertEqual(format_selection([7]), '7')