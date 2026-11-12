"""
The workload pages behind the Overview's tiles (12 Nov 2026): each page lists
exactly the jobs its tile counts, because both use workload_filter.
"""
from django.test import TestCase
from django.utils import timezone

from apps.jobs.selectors.stats_selectors import get_active_workload
from apps.jobs.selectors.workload_selectors import (
    WORKLOAD_VIEWS, get_workload_list, workload_filter,
)
from apps.organization.models import Branch


class WorkloadTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.branch = Branch.objects.first()
        if self.branch is None:
            self.skipTest('no branch in the test database')

    def test_every_page_lists_exactly_what_its_tile_counts(self):
        counts = get_active_workload(self.branch)
        for view in WORKLOAD_VIEWS:
            listed = get_workload_list(self.branch, view)
            self.assertEqual(listed['summary']['count'], counts[view], view)

    def test_an_unknown_page_is_refused(self):
        with self.assertRaises(ValueError):
            workload_filter('lunch', timezone.now())
