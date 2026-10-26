"""Links between people and organisations: several per person, one open per pair, ended not deleted."""

from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.customers.models import CustomerProfile, Membership


class MembershipTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.edward = CustomerProfile.objects.create(first_name='Edward', last_name='Appiah',
                                                    phone='+233242884488', customer_type='INDIVIDUAL')
        cls.piwak = CustomerProfile.objects.create(first_name='Edward', company_name='Piwak Construction Ltd',
                                                   phone='+233558496250', customer_type='BUSINESS')
        cls.church = CustomerProfile.objects.create(first_name='Office', company_name='Grace Church',
                                                    phone='+233201112233', customer_type='INSTITUTION')

    def test_one_person_several_organisations(self):
        Membership.objects.create(person=self.edward, organisation=self.piwak, role='REP')
        Membership.objects.create(person=self.edward, organisation=self.church)
        self.assertEqual(self.edward.memberships.count(), 2)
        self.assertEqual(self.piwak.members.get().role, 'REP')

    def test_only_one_open_link_per_pair(self):
        Membership.objects.create(person=self.edward, organisation=self.piwak)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Membership.objects.create(person=self.edward, organisation=self.piwak)

    def test_leaving_ends_the_link_and_keeps_it(self):
        link = Membership.objects.create(person=self.edward, organisation=self.piwak)
        link.end()
        link.refresh_from_db()
        self.assertFalse(link.active)
        self.assertEqual(Membership.objects.filter(person=self.edward).count(), 1)
        # And they can be linked again later.
        Membership.objects.create(person=self.edward, organisation=self.piwak)
        self.assertEqual(self.edward.memberships.filter(ended_at__isnull=True).count(), 1)