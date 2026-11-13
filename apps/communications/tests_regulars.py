"""
Regulars (13 Nov 2026): when Octos asks for a customer's details.
"""
from django.test import SimpleTestCase

from apps.communications.assistant.regulars import decide


def ask(**kw):
    base = dict(registered=False, visits_in_window=4, at_counter=False, declined_recently=False, asked_recently=False)
    base.update(kw)
    return decide(**base)[0]


class RegularsTests(SimpleTestCase):
    def test_the_fourth_visit_in_72_hours_asks(self):
        self.assertTrue(ask())

    def test_three_visits_do_not(self):
        self.assertFalse(ask(visits_in_window=3))

    def test_a_registered_customer_is_never_asked(self):
        self.assertFalse(ask(registered=True))

    def test_never_while_at_the_counter(self):
        self.assertFalse(ask(at_counter=True))

    def test_a_no_thanks_holds_for_30_days(self):
        self.assertFalse(ask(declined_recently=True))

    def test_once_asked_not_again_for_72_hours(self):
        self.assertFalse(ask(asked_recently=True))
