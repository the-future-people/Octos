import datetime
from decimal import Decimal

from django.test import TestCase

from apps.jobs.models import Service
from apps.organization.models import Branch
from apps.production.models import (
    Machine, MachineType, ServiceStation, Station,
)


class BranchCapabilityTests(TestCase):
    """
    Which branches can do this work, and when each would finish.

    Not the reroute engine: that moves a job that already has a home
    and scores branches on a weighted guess. This answers a narrower
    question honestly — can this branch print this today — and leaves
    the choice to the customer, who knows whether sooner or nearer
    matters more.

    A branch is offered only when it genuinely can. A machine marked
    down is a branch that cannot, today, whatever it owns.
    """

    @classmethod
    def setUpTestData(cls):
        from apps.organization.models import Region

        cls.region = Region.objects.filter().first() or None

        cls.westland = cls._branch('Westland', 'CAPW')
        cls.spintex = cls._branch('Spintex', 'CAPS')

        cls.print_st = Station.objects.create(code='PRINT', name='Printing', sequence=1)
        cls.finish_st = Station.objects.create(code='FINISH', name='Finishing', sequence=5)

        cls.large = MachineType.objects.create(
            code='LARGE_FORMAT', name='Large format printer',
            station=cls.print_st,
        )
        cls.press = MachineType.objects.create(
            code='DIGITAL_PRESS', name='Digital press',
            station=cls.print_st, max_paper_size='A3',
        )

        cls.flexy = Service.objects.create(
            name='Capability Flexy', code='CAPFLEXY',
            category='PRODUCTION', unit='PER_SQFT',
            requires_file_upload=True, is_active=True,
        )
        ServiceStation.objects.create(
            service=cls.flexy, station=cls.print_st, machine_type=cls.large,
            sequence=1, setup_minutes=Decimal('12'), minutes_per_unit=Decimal('0.143'),
        )
        # Hand work: no machine type, so any branch can do this step.
        ServiceStation.objects.create(
            service=cls.flexy, station=cls.finish_st, machine_type=None,
            sequence=2, setup_minutes=Decimal('5'), minutes_per_unit=Decimal('0.25'),
        )

        cls.typing = Service.objects.create(
            name='Capability Typing', code='CAPTYPE',
            category='INSTANT', unit='PER_PAGE', is_active=True,
        )
        ServiceStation.objects.create(
            service=cls.typing, station=cls.finish_st, machine_type=None,
            sequence=1, setup_minutes=Decimal('0'), minutes_per_unit=Decimal('5'),
        )

    @classmethod
    def _branch(cls, name, code):
        return Branch.objects.create(
            name=name, code=code,
            is_headquarters=False, is_regional_hq=False,
            address=f'{name} Road',
            capacity_score=100, current_load=0, is_active=True,
            opening_time=datetime.time(7, 30),
            closing_time=datetime.time(19, 30),
            vat_registered=False, vat_rate=Decimal('0'),
            nhil_rate=Decimal('0'), getfund_rate=Decimal('0'),
        )

    def _printer_at(self, branch, machine_type=None, available=True,
                    width_mm=1900):
        return Machine.objects.create(
            branch=branch, machine_type=machine_type or self.large,
            name=f'{branch.code} printer',
            max_width_mm=width_mm,
            is_active=True, is_available=available,
        )

    def _lines(self, service=None, quantity=18, pages=1):
        return [(service or self.flexy, quantity, pages)]

    # ── Can it be done here at all ─────────────────────────────────

    def test_a_branch_with_the_machine_is_offered(self):
        from apps.production.capability import branch_options

        self._printer_at(self.westland)
        options = branch_options(self._lines())

        self.assertEqual([o['branch'].code for o in options], ['CAPW'])

    def test_a_branch_without_the_machine_is_not_offered(self):
        """
        Spintex has a press and no large format. It cannot print a
        banner, however much capacity it has.
        """
        from apps.production.capability import branch_options

        self._printer_at(self.westland)
        self._printer_at(self.spintex, machine_type=self.press)

        options = branch_options(self._lines())
        self.assertEqual([o['branch'].code for o in options], ['CAPW'])

    def test_a_machine_marked_down_takes_its_branch_out(self):
        """
        It cannot do the work today, which is the only question the
        customer is asking.
        """
        from apps.production.capability import branch_options

        self._printer_at(self.westland, available=False)
        self.assertEqual(branch_options(self._lines()), [])

    def test_hand_work_needs_no_machine(self):
        """A service whose route names no machine can be done anywhere."""
        from apps.production.capability import branch_options

        options = branch_options(self._lines(service=self.typing, quantity=3))
        self.assertEqual(
            {o['branch'].code for o in options}, {'CAPW', 'CAPS'},
        )

    def test_an_inactive_branch_is_never_offered(self):
        from apps.production.capability import branch_options

        self._printer_at(self.westland)
        self.westland.is_active = False
        self.westland.save()

        self.assertEqual(branch_options(self._lines()), [])

    # ── Width ──────────────────────────────────────────────────────

    def test_a_banner_wider_than_the_machine_rules_the_branch_out(self):
        """
        Westland's 6ft cannot print 2400mm however long it is given.
        Spintex's 10ft can.
        """
        from apps.production.capability import branch_options

        self._printer_at(self.westland, width_mm=1900)
        self._printer_at(self.spintex, width_mm=3200)

        options = branch_options(self._lines(), width_mm=2400)
        self.assertEqual([o['branch'].code for o in options], ['CAPS'])

    def test_a_banner_within_the_machine_leaves_both_in(self):
        from apps.production.capability import branch_options

        self._printer_at(self.westland, width_mm=1900)
        self._printer_at(self.spintex, width_mm=3200)

        options = branch_options(self._lines(), width_mm=1500)
        self.assertEqual(
            {o['branch'].code for o in options}, {'CAPW', 'CAPS'},
        )

    # ── When ───────────────────────────────────────────────────────

    def test_each_option_says_when_it_would_be_ready(self):
        from apps.production.capability import branch_options

        self._printer_at(self.westland)
        option = branch_options(self._lines())[0]

        self.assertIsNotNone(option['ready_at'])
        self.assertGreater(option['minutes'], 0)
        self.assertIn(option['confidence'], ('estimated', 'measured'))

    def test_options_come_back_soonest_first(self):
        """
        The customer decides whether sooner or nearer matters. Our job
        is to put the quickest first and show them the difference.
        """
        from apps.jobs.models import Job, JobLineItem
        from apps.production.capability import branch_options

        self._printer_at(self.westland)
        self._printer_at(self.spintex)

        # A day's work queued at Westland, so Spintex is quicker.
        busy = Job.objects.create(
            branch=self.westland, job_type='PRODUCTION',
            status=Job.PENDING_PAYMENT, title='Queue filler',
            estimated_cost=Decimal('100'),
            payment_state='DEPOSIT_PAID', work_state='RECEIVED',
            handover_state='AWAITING_COLLECTION',
        )
        JobLineItem.objects.create(
            job=busy, service=self.flexy, quantity=2000, pages=1,
            unit_price=Decimal('3.25'), line_total=Decimal('6500'),
        )

        options = branch_options(self._lines())
        self.assertEqual(options[0]['branch'].code, 'CAPS')

    # ── Why not ────────────────────────────────────────────────────

    def test_the_reasons_branches_were_ruled_out_come_back_too(self):
        """
        An empty list tells a customer nothing. 'No branch can print a
        banner that wide today' tells them what to change.
        """
        from apps.production.capability import assess

        self._printer_at(self.westland, width_mm=1900)
        result = assess(self._lines(), width_mm=2400)

        self.assertEqual(result['options'], [])
        self.assertTrue(result['refusals'])
        self.assertIn('wide', str(result['refusals']).lower())