"""
The nightly proforma tasks run (8 Nov 2026). expire_proformas called a method
renamed long ago and crashed every night unseen; a rename now fails a test.
"""
from django.test import TestCase


class NightlyProformaTasksTests(TestCase):

    def test_expire_proformas_runs(self):
        from apps.jobs.tasks import expire_proformas
        expire_proformas()

    def test_remind_open_proformas_runs(self):
        from apps.jobs.tasks import remind_open_proformas
        remind_open_proformas()
