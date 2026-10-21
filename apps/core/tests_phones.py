"""One rule for phone numbers: international form, Ghana by default, every country respected."""

from django.test import SimpleTestCase

from apps.core.phones import check, display, is_ghanaian, lookup_forms, to_international


class InternationalTests(SimpleTestCase):

    def test_every_ghanaian_way_of_writing_it_is_one_number(self):
        for typed in ('0244123456', '024 412 3456', '233244123456', '+233 24 412 3456', '00233244123456'):
            self.assertEqual(to_international(typed), '+233244123456', typed)

    def test_foreign_numbers_are_kept_as_their_own_country(self):
        self.assertEqual(to_international('+2348031234567'), '+2348031234567')
        self.assertEqual(to_international('+1 514 582 8114'), '+15145828114')
        self.assertEqual(to_international('+98 912 452 4576'), '+989124524576')
        self.assertEqual(to_international('+44 7911 123456'), '+447911123456')

    def test_what_is_not_a_number_is_nothing(self):
        for typed in ('', 'abc', '059012712', '12345'):
            self.assertIsNone(to_international(typed), typed)


class CheckTests(SimpleTestCase):

    def test_a_good_number_has_no_problem(self):
        self.assertEqual(check('0244123456'), ('+233244123456', None))

    def test_a_digit_short_says_so(self):
        number, problem = check('059012712')
        self.assertIsNone(number)
        self.assertIn('one digit short', problem)

    def test_a_foreign_number_without_its_code_is_told_how(self):
        number, problem = check('07911123456')
        self.assertIsNone(number)
        self.assertIn('country code', problem)

    def test_nothing_typed(self):
        self.assertEqual(check('  '), (None, 'Enter a phone number.'))


class DisplayTests(SimpleTestCase):

    def test_ghanaian_numbers_the_familiar_way(self):
        self.assertEqual(display('+233244123456'), '024 412 3456')
        self.assertTrue(is_ghanaian('+233244123456'))

    def test_foreign_numbers_with_their_code(self):
        self.assertTrue(display('+15145828114').startswith('+1'))
        self.assertFalse(is_ghanaian('+15145828114'))


class LookupFormsTests(SimpleTestCase):

    def test_a_ghanaian_number_is_looked_for_in_every_old_form(self):
        forms = lookup_forms('024 412 3456')
        for stored in ('+233244123456', '233244123456', '0244123456', '244123456'):
            self.assertIn(stored, forms)

    def test_a_foreign_number_is_found_however_it_was_typed(self):
        self.assertIn('+989124524576', lookup_forms('+98 912 452 4576'))
        self.assertIn('+989124524576', lookup_forms('00989124524576'))