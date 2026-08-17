"""
Automated regression tests for the Jobs lifecycle fixes:
  - INTAKE_HELD transition map integrity (status_engine.py)
  - Handover resolution routed through JobStatusEngine (audit trail)
  - Handover dispute flagging + RM escalation
  - Draft discard routed through JobStatusEngine (audit trail)
  - Credit engine consolidation (cashier_service.py)

All fixtures are constructed from scratch in setUpTestData, since
Django's TestCase always runs against a fresh, empty test database —
see tasks/lessons.md for why this differs from the one-off shell
verification script.

Run inside Docker:
    docker compose exec web python manage.py test apps.jobs.tests
"""

import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.organization.models import Branch
from apps.accounts.models import CustomUser, Role
from apps.customers.models import CustomerProfile
from apps.jobs.models import Job, JobStatusLog, Service
from apps.finance.models import CreditAccount, DailySalesSheet
from apps.jobs.status_engine import JobStatusEngine
from apps.jobs.api.views import (
    ResolveHandoverView, DisputeHandoverView, DiscardDraftView,
)


def make_request(method, user):
    """Build an authenticated DRF request — force_authenticate bypasses
    JWT machinery entirely, which is what we want when testing view
    logic + permissions rather than the auth backend itself."""
    rf = APIRequestFactory()
    req = getattr(rf, method)('/fake-url/')
    force_authenticate(req, user=user)
    return req


class JobsFixtureMixin:
    """Builds a complete, self-contained set of fixtures from scratch —
    no dependency on staging/dev data existing."""

    @classmethod
    def setUpTestData(cls):
        cls.bm_role = Role.objects.create(
            name='BRANCH_MANAGER', display_name='Branch Manager',
            is_constrained=False, scope='BRANCH',
        )
        cls.cashier_role = Role.objects.create(
            name='CASHIER', display_name='Cashier',
            is_constrained=False, scope='BRANCH',
        )
        cls.attendant_role = Role.objects.create(
            name='ATTENDANT', display_name='Attendant',
            is_constrained=False, scope='BRANCH',
        )
        cls.coordinator_role = Role.objects.create(
            name='FLOW_COORDINATOR', display_name='Flow Coordinator',
            is_constrained=False, scope='BRANCH',
        )

        cls.branch = Branch.objects.create(
            name='Test Branch', code='TSTB',
            is_headquarters=False, is_regional_hq=False,
            address='123 Test Street',
            capacity_score=100, current_load=0, is_active=True,
            opening_time=datetime.time(7, 30),
            closing_time=datetime.time(19, 30),
            vat_registered=False, vat_rate=Decimal('0'),
            nhil_rate=Decimal('0'), getfund_rate=Decimal('0'),
        )
        cls.other_branch = Branch.objects.create(
            name='Other Test Branch', code='OTHB',
            is_headquarters=False, is_regional_hq=False,
            address='456 Other Street',
            capacity_score=100, current_load=0, is_active=True,
            opening_time=datetime.time(7, 30),
            closing_time=datetime.time(19, 30),
            vat_registered=False, vat_rate=Decimal('0'),
            nhil_rate=Decimal('0'), getfund_rate=Decimal('0'),
        )

        cls.bm = CustomUser(
            employee_id='TST-BM-001',
            first_name='Test', last_name='Manager',
            email='bm@test.local',
            employment_status='ACTIVE',
            is_active=True, is_staff=False, is_superuser=False,
            is_clocked_in=False, must_change_password=False,
            is_business_owner=False, download_pin_set=False,
            branch=cls.branch, role=cls.bm_role,
        )
        cls.bm.set_password('test-pass-123')
        cls.bm.save()

        cls.cashier = CustomUser(
            employee_id='TST-CSH-001',
            first_name='Test', last_name='Cashier',
            email='cashier@test.local',
            employment_status='ACTIVE',
            is_active=True, is_staff=False, is_superuser=False,
            is_clocked_in=False, must_change_password=False,
            is_business_owner=False, download_pin_set=False,
            branch=cls.branch, role=cls.cashier_role,
        )
        cls.cashier.set_password('test-pass-123')
        cls.cashier.save()

        cls.attendant = CustomUser(
            employee_id='TST-ATT-001',
            first_name='Test', last_name='Attendant',
            email='attendant@test.local',
            employment_status='ACTIVE',
            is_active=True, is_staff=False, is_superuser=False,
            is_clocked_in=False, must_change_password=False,
            is_business_owner=False, download_pin_set=False,
            branch=cls.branch, role=cls.attendant_role,
        )
        cls.attendant.set_password('test-pass-123')
        cls.attendant.save()

        cls.coordinator = CustomUser(
            employee_id='TST-CRD-001',
            first_name='Test', last_name='Coordinator',
            email='coordinator@test.local',
            employment_status='ACTIVE',
            is_active=True, is_staff=False, is_superuser=False,
            is_clocked_in=False, must_change_password=False,
            is_business_owner=False, download_pin_set=False,
            branch=cls.branch, role=cls.coordinator_role,
        )
        cls.coordinator.set_password('test-pass-123')
        cls.coordinator.save()

        cls.service = Service.objects.create(
            name='Test Photocopy', code='TSTSVC',
            category='INSTANT', unit='PER_PAGE',
            requires_design=False, requires_file_upload=False,
            is_active=True,
        )

        cls.today = timezone.localdate()
        cls.sheet, _ = DailySalesSheet.objects.get_or_create(
            branch=cls.branch, date=cls.today,
            defaults={'status': DailySalesSheet.Status.OPEN},
        )


class TransitionMapIntegrityTests(JobsFixtureMixin, TestCase):
    """Section A — INTAKE_HELD must be a real, correctly-scoped state
    in all three job-type transition maps."""

    def _make_intake_held_job(self, job_type):
        return Job.objects.create(
            branch=self.branch, job_type=job_type, status=Job.INTAKE_HELD,
            title='Test job', intake_by=self.bm, estimated_cost=50,
            post_closing=True, post_closing_reason='Automated test',
        )

    def test_intake_held_to_pending_payment_legal_for_all_job_types(self):
        for job_type in ['INSTANT', 'PRODUCTION', 'DESIGN']:
            with self.subTest(job_type=job_type):
                job = self._make_intake_held_job(job_type)
                engine = JobStatusEngine(job)
                self.assertTrue(engine.can_transition('PENDING_PAYMENT'))

    def test_intake_held_to_complete_illegal_for_all_job_types(self):
        for job_type in ['INSTANT', 'PRODUCTION', 'DESIGN']:
            with self.subTest(job_type=job_type):
                job = self._make_intake_held_job(job_type)
                engine = JobStatusEngine(job)
                self.assertFalse(engine.can_transition('COMPLETE'))

    def test_illegal_transition_raises_valueerror(self):
        for job_type in ['INSTANT', 'PRODUCTION', 'DESIGN']:
            with self.subTest(job_type=job_type):
                job = self._make_intake_held_job(job_type)
                engine = JobStatusEngine(job)
                with self.assertRaises(ValueError):
                    engine.transition('COMPLETE', actor=self.bm)


class ResolveHandoverViewTests(JobsFixtureMixin, TestCase):
    """Section B — cashier affirms an INTAKE_HELD job."""

    def setUp(self):
        self.job = Job.objects.create(
            branch=self.branch, job_type='INSTANT', status=Job.INTAKE_HELD,
            title='Handover affirm test', intake_by=self.bm, estimated_cost=75,
            post_closing=True, post_closing_reason='Automated test',
            daily_sheet=None,
        )
        self.view = ResolveHandoverView.as_view()

    def test_resolve_handover_success(self):
        log_count_before = JobStatusLog.objects.filter(job=self.job).count()

        req = make_request('post', self.cashier)
        resp = self.view(req, pk=self.job.pk)
        self.job.refresh_from_db()

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.job.status, 'PENDING_PAYMENT')
        self.assertIsNotNone(self.job.daily_sheet_id)
        self.assertIsNotNone(self.job.handover_resolved_at)
        self.assertEqual(self.job.handover_resolved_by_id, self.cashier.id)
        self.assertEqual(
            JobStatusLog.objects.filter(
                job=self.job, from_status='INTAKE_HELD', to_status='PENDING_PAYMENT',
            ).count(),
            log_count_before + 1,
        )

    def test_resolve_handover_twice_returns_404(self):
        req1 = make_request('post', self.cashier)
        self.view(req1, pk=self.job.pk)

        req2 = make_request('post', self.cashier)
        resp2 = self.view(req2, pk=self.job.pk)
        self.assertEqual(resp2.status_code, 404)

    def test_resolve_handover_cross_branch_returns_404(self):
        cross_job = Job.objects.create(
            branch=self.other_branch, job_type='INSTANT', status=Job.INTAKE_HELD,
            title='Cross-branch test', intake_by=self.bm, estimated_cost=40,
            post_closing=True, post_closing_reason='Automated test',
        )
        req = make_request('post', self.cashier)  # cashier belongs to self.branch
        resp = self.view(req, pk=cross_job.pk)
        self.assertEqual(resp.status_code, 404)


class DisputeHandoverViewTests(JobsFixtureMixin, TestCase):
    """Section C — cashier reports BM did not hand over cash."""

    def setUp(self):
        self.job = Job.objects.create(
            branch=self.branch, job_type='INSTANT', status=Job.INTAKE_HELD,
            title='Handover dispute test', intake_by=self.bm, estimated_cost=60,
            post_closing=True, post_closing_reason='Automated test',
            daily_sheet=None,
        )
        self.view = DisputeHandoverView.as_view()

    def test_dispute_handover_success(self):
        req = make_request('post', self.cashier)
        resp = self.view(req, pk=self.job.pk)
        self.job.refresh_from_db()

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.job.status, 'INTAKE_HELD')  # flag, not a transition
        self.assertTrue(self.job.handover_disputed)
        self.assertIsNotNone(self.job.handover_disputed_at)
        self.assertEqual(self.job.handover_disputed_by_id, self.cashier.id)

    def test_dispute_handover_twice_returns_400(self):
        req1 = make_request('post', self.cashier)
        self.view(req1, pk=self.job.pk)

        req2 = make_request('post', self.cashier)
        resp2 = self.view(req2, pk=self.job.pk)
        self.assertEqual(resp2.status_code, 400)


class DiscardDraftViewTests(JobsFixtureMixin, TestCase):
    """Section E — discarding a draft must now log through the engine."""

    def setUp(self):
        self.job = Job.objects.create(
            branch=self.branch, job_type='INSTANT', status=Job.DRAFT,
            title='Draft discard test', intake_by=self.bm, estimated_cost=30,
        )
        self.view = DiscardDraftView.as_view()

    def test_discard_draft_logs_transition(self):
        log_count_before = JobStatusLog.objects.filter(job=self.job).count()

        req = make_request('post', self.bm)
        resp = self.view(req, pk=self.job.pk)
        self.job.refresh_from_db()

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.job.status, 'CANCELLED')
        self.assertIsNotNone(self.job.abandoned_at)
        self.assertEqual(
            JobStatusLog.objects.filter(
                job=self.job, from_status='DRAFT', to_status='CANCELLED',
            ).count(),
            log_count_before + 1,
        )


class CreditEngineRegressionTests(JobsFixtureMixin, TestCase):
    """Section F — confirm the credit engine consolidation didn't break
    full credit and now actually fixes partial credit."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.customer = CustomerProfile.objects.create(
            phone='0555000111', affiliation_active=True,
            customer_type=CustomerProfile.INDIVIDUAL,
            visit_count=0, total_spend=Decimal('0'),
            tier=CustomerProfile.REGULAR, confidence_score=0,
            is_priority=False, is_walkin=False,
            first_name='Test', last_name='Customer',
        )
        cls.credit_account = CreditAccount.objects.create(
            customer=cls.customer,
            account_type=CreditAccount.Status.__class__ and 'INDIVIDUAL',
            status='ACTIVE',
            credit_limit=Decimal('500.00'),
            current_balance=Decimal('0.00'),
            payment_terms=30,
        )

    def test_full_credit_payment_still_works(self):
        from apps.jobs.services.cashier_service import confirm_payment

        job = Job.objects.create(
            branch=self.branch, job_type='INSTANT', status=Job.PENDING_PAYMENT,
            title='Full credit test', intake_by=self.bm,
            estimated_cost=Decimal('25.00'), daily_sheet=self.sheet,
        )

        result = confirm_payment(
            job=job,
            validated_data={
                'deposit_percentage': 100,
                'payment_method': 'CREDIT',
                'credit_account_id': self.credit_account.pk,
            },
            actor=self.cashier,
        )

        job.refresh_from_db()
        self.assertEqual(job.status, 'COMPLETE')
        self.assertEqual(job.payment_method, 'CREDIT')
        self.assertEqual(result['payment_method'], 'CREDIT')

    def test_partial_credit_payment_now_succeeds(self):
        from apps.jobs.services.cashier_service import confirm_payment

        job = Job.objects.create(
            branch=self.branch, job_type='INSTANT', status=Job.PENDING_PAYMENT,
            title='Partial credit test', intake_by=self.bm,
            estimated_cost=Decimal('40.00'), daily_sheet=self.sheet,
        )
        balance_before = self.credit_account.current_balance

        result = confirm_payment(
            job=job,
            validated_data={
                'deposit_percentage': 50,
                'payment_method': 'CASH',
                'cash_tendered': Decimal('20.00'),
                'partial_credit_amount': Decimal('20.00'),
                'partial_credit_account': self.credit_account.pk,
            },
            actor=self.cashier,
        )

        self.credit_account.refresh_from_db()
        job.refresh_from_db()

        self.assertEqual(
            self.credit_account.current_balance,
            balance_before + Decimal('20.00'),
        )
        self.assertEqual(job.partial_credit_amount, Decimal('20.00'))
        self.assertIn('partial_credit_amount', result)

class WorkAxisTests(JobsFixtureMixin, TestCase):
    """
    The production work ladder. Nothing in production has ever exercised
    this — every job at Westland is INSTANT — so these tests are the only
    evidence the ladder works at all.
    """

    def _production_job(self, **overrides):
        defaults = dict(
            branch=self.branch, job_type='PRODUCTION',
            status=Job.PENDING_PAYMENT, title='Work axis test',
            intake_by=self.attendant, estimated_cost=Decimal('100.00'),
            daily_sheet=self.sheet,
            payment_state='DEPOSIT_PAID',
            work_state='RECEIVED',
            handover_state='AWAITING_COLLECTION',
        )
        defaults.update(overrides)
        return Job.objects.create(**defaults)

    def test_full_production_ladder(self):
        job    = self._production_job()
        engine = JobStatusEngine(job)
        for state in ['IN_PRODUCTION', 'FINISHING', 'QUALITY_CHECK', 'DONE']:
            engine.move_work(state, actor=self.coordinator)
            job.refresh_from_db()
            self.assertEqual(job.work_state, state)

    def test_cannot_skip_a_stage(self):
        job = self._production_job()
        with self.assertRaises(ValueError):
            JobStatusEngine(job).move_work('DONE', actor=self.coordinator)

    def test_instant_job_goes_straight_to_done(self):
        job = self._production_job(job_type='INSTANT')
        JobStatusEngine(job).move_work('DONE', actor=self.coordinator)
        job.refresh_from_db()
        self.assertEqual(job.work_state, 'DONE')

    def test_cashier_cannot_move_work(self):
        job = self._production_job()
        with self.assertRaises(PermissionError):
            JobStatusEngine(job).move_work('IN_PRODUCTION', actor=self.cashier)

    def test_bm_may_override_any_axis(self):
        job = self._production_job()
        JobStatusEngine(job).move_work('IN_PRODUCTION', actor=self.bm)
        job.refresh_from_db()
        self.assertEqual(job.work_state, 'IN_PRODUCTION')

    def test_unpaid_production_cannot_start(self):
        job = self._production_job(payment_state='UNPAID')
        with self.assertRaises(ValueError):
            JobStatusEngine(job).move_work('IN_PRODUCTION', actor=self.coordinator)

    def test_work_move_logs_with_axis(self):
        job = self._production_job()
        JobStatusEngine(job).move_work('IN_PRODUCTION', actor=self.coordinator)
        log = JobStatusLog.objects.filter(job=job).first()
        self.assertEqual(log.axis, 'WORK')
        self.assertEqual(log.from_status, 'RECEIVED')
        self.assertEqual(log.to_status, 'IN_PRODUCTION')


class HandoverAxisTests(JobsFixtureMixin, TestCase):
    """
    The rule that protects the money: an attendant can never release an
    unpaid job.
    """

    def _ready_job(self, **overrides):
        defaults = dict(
            branch=self.branch, job_type='PRODUCTION',
            status=Job.PENDING_PAYMENT, title='Handover test',
            intake_by=self.attendant, estimated_cost=Decimal('100.00'),
            daily_sheet=self.sheet,
            payment_state='SETTLED',
            work_state='DONE',
            handover_state='AWAITING_COLLECTION',
        )
        defaults.update(overrides)
        return Job.objects.create(**defaults)

    def test_settled_and_done_can_be_handed_over(self):
        job = self._ready_job()
        JobStatusEngine(job).move_handover('HANDED_OVER', actor=self.attendant)
        job.refresh_from_db()
        self.assertEqual(job.handover_state, 'HANDED_OVER')
        self.assertIsNotNone(job.handed_over_at)
        self.assertEqual(job.handed_over_by_id, self.attendant.id)

    def test_unpaid_job_cannot_be_released(self):
        job = self._ready_job(payment_state='UNPAID')
        with self.assertRaises(ValueError):
            JobStatusEngine(job).move_handover('HANDED_OVER', actor=self.attendant)

    def test_deposit_paid_job_cannot_be_released(self):
        job = self._ready_job(payment_state='DEPOSIT_PAID')
        with self.assertRaises(ValueError):
            JobStatusEngine(job).move_handover('HANDED_OVER', actor=self.attendant)

    def test_unfinished_job_cannot_be_released(self):
        job = self._ready_job(work_state='FINISHING')
        with self.assertRaises(ValueError):
            JobStatusEngine(job).move_handover('HANDED_OVER', actor=self.attendant)

    def test_coordinator_cannot_hand_over(self):
        job = self._ready_job()
        with self.assertRaises(PermissionError):
            JobStatusEngine(job).move_handover('HANDED_OVER', actor=self.coordinator)

    def test_handover_derives_legacy_complete(self):
        job = self._ready_job()
        JobStatusEngine(job).move_handover('HANDED_OVER', actor=self.attendant)
        job.refresh_from_db()
        self.assertEqual(job.status, 'COMPLETE')


class PaymentAxisTests(JobsFixtureMixin, TestCase):

    def _job(self, **overrides):
        defaults = dict(
            branch=self.branch, job_type='PRODUCTION',
            status=Job.PENDING_PAYMENT, title='Payment axis test',
            intake_by=self.attendant, estimated_cost=Decimal('100.00'),
            daily_sheet=self.sheet,
            payment_state='UNPAID',
            work_state='RECEIVED',
            handover_state='AWAITING_COLLECTION',
        )
        defaults.update(overrides)
        return Job.objects.create(**defaults)

    def test_cashier_can_take_a_deposit_then_settle(self):
        job    = self._job()
        engine = JobStatusEngine(job)
        engine.move_payment('DEPOSIT_PAID', actor=self.cashier)
        engine.move_payment('SETTLED', actor=self.cashier)
        job.refresh_from_db()
        self.assertEqual(job.payment_state, 'SETTLED')

    def test_settled_is_terminal(self):
        job = self._job(payment_state='SETTLED')
        with self.assertRaises(ValueError):
            JobStatusEngine(job).move_payment('DEPOSIT_PAID', actor=self.cashier)

    def test_attendant_cannot_move_payment(self):
        job = self._job()
        with self.assertRaises(PermissionError):
            JobStatusEngine(job).move_payment('SETTLED', actor=self.attendant)

    def test_unrecognised_role_owns_nothing(self):
        no_role = CustomUser(
            employee_id='TST-NUL-001',
            first_name='No', last_name='Role',
            email='norole@test.local',
            employment_status='ACTIVE', is_active=True,
            branch=self.branch, role=None,
        )
        no_role.set_password('test-pass-123')
        no_role.save()

        job = self._job()
        with self.assertRaises(PermissionError):
            JobStatusEngine(job).move_payment('SETTLED', actor=no_role)


class HaltTests(JobsFixtureMixin, TestCase):

    def _in_production_job(self, **overrides):
        defaults = dict(
            branch=self.branch, job_type='PRODUCTION',
            status=Job.PENDING_PAYMENT, title='Halt test',
            intake_by=self.attendant, estimated_cost=Decimal('100.00'),
            daily_sheet=self.sheet,
            payment_state='DEPOSIT_PAID',
            work_state='FINISHING',
            handover_state='AWAITING_COLLECTION',
        )
        defaults.update(overrides)
        return Job.objects.create(**defaults)

    def test_halt_preserves_the_stage(self):
        job  = self._in_production_job()
        halt = JobStatusEngine(job).halt('MACHINE_BREAKDOWN', actor=self.coordinator)
        job.refresh_from_db()
        self.assertEqual(halt.work_state_at_halt, 'FINISHING')
        self.assertEqual(job.work_state, 'FINISHING')

    def test_halted_job_cannot_move_work(self):
        job    = self._in_production_job()
        engine = JobStatusEngine(job)
        engine.halt('MATERIALS_OUT', actor=self.coordinator)
        with self.assertRaises(ValueError):
            engine.move_work('QUALITY_CHECK', actor=self.coordinator)

    def test_resume_reopens_the_same_stage(self):
        job    = self._in_production_job()
        engine = JobStatusEngine(job)
        engine.halt('MACHINE_BREAKDOWN', actor=self.coordinator)
        engine.resume(actor=self.coordinator)
        job.refresh_from_db()
        self.assertFalse(engine.is_halted())
        engine.move_work('QUALITY_CHECK', actor=self.coordinator)
        job.refresh_from_db()
        self.assertEqual(job.work_state, 'QUALITY_CHECK')

    def test_cannot_halt_twice(self):
        job    = self._in_production_job()
        engine = JobStatusEngine(job)
        engine.halt('MACHINE_BREAKDOWN', actor=self.coordinator)
        with self.assertRaises(ValueError):
            engine.halt('MATERIALS_OUT', actor=self.coordinator)

    def test_payment_still_moves_while_halted(self):
        job    = self._in_production_job()
        engine = JobStatusEngine(job)
        engine.halt('MACHINE_BREAKDOWN', actor=self.coordinator)
        engine.move_payment('SETTLED', actor=self.cashier)
        job.refresh_from_db()
        self.assertEqual(job.payment_state, 'SETTLED')

    def test_halts_are_kept_not_overwritten(self):
        job    = self._in_production_job()
        engine = JobStatusEngine(job)
        engine.halt('MACHINE_BREAKDOWN', actor=self.coordinator)
        engine.resume(actor=self.coordinator)
        engine.halt('MATERIALS_OUT', actor=self.coordinator)
        self.assertEqual(job.halts.count(), 2)

class HaltedCounterTests(JobsFixtureMixin, TestCase):
    """
    A LEFT JOIN gives a NULL resumed_at to jobs that have no halts at all,
    so filtering on halts__resumed_at__isnull=True counted every job in the
    branch as halted. It reached production and read 29 of 29 halted.
    """

    def setUp(self):
        common = dict(
            branch=self.branch, job_type='PRODUCTION',
            status=Job.PENDING_PAYMENT, intake_by=self.attendant,
            estimated_cost=Decimal('50.00'), daily_sheet=self.sheet,
            payment_state='DEPOSIT_PAID', work_state='IN_PRODUCTION',
            handover_state='AWAITING_COLLECTION',
        )
        self.never_halted = Job.objects.create(title='Never halted', **common)
        self.halted       = Job.objects.create(title='Halted', **common)
        self.resumed      = Job.objects.create(title='Resumed', **common)

        JobStatusEngine(self.halted).halt('MATERIALS_OUT', actor=self.coordinator)
        engine = JobStatusEngine(self.resumed)
        engine.halt('MACHINE_BREAKDOWN', actor=self.coordinator)
        engine.resume(actor=self.coordinator)

    def test_only_actively_halted_jobs_are_counted(self):
        from apps.jobs.selectors.stats_selectors import get_branch_stats
        stats = get_branch_stats(self.branch)
        self.assertEqual(stats['halted'], 1)
        self.assertEqual(stats['in_production'], 3)

    def test_halted_queue_returns_only_the_halted_job(self):
        from apps.jobs.models import JobHalt
        halted_ids = set(
            Job.objects.filter(
                branch=self.branch,
                pk__in=JobHalt.objects.filter(
                    resumed_at__isnull=True,
                ).values('job_id'),
            ).values_list('pk', flat=True)
        )
        self.assertEqual(halted_ids, {self.halted.pk})

    def test_a_resumed_job_is_not_halted(self):
        from apps.jobs.selectors.stats_selectors import get_branch_stats
        JobStatusEngine(self.halted).resume(actor=self.coordinator)
        self.assertEqual(get_branch_stats(self.branch)['halted'], 0)

class VerificationTests(JobsFixtureMixin, TestCase):
    """
    A walk-in needs no verification — the customer was standing there. A
    remote order has nobody to ask, so someone opens the file before five
    hundred flyers are printed from it.
    """

    def _job(self, channel, **overrides):
        defaults = dict(
            branch=self.branch, job_type='PRODUCTION',
            status=Job.PENDING_PAYMENT, title='Verification test',
            intake_by=self.attendant, estimated_cost=Decimal('100.00'),
            daily_sheet=self.sheet, intake_channel=channel,
            payment_state='DEPOSIT_PAID', work_state='RECEIVED',
            handover_state='AWAITING_COLLECTION',
        )
        defaults.update(overrides)
        return Job.objects.create(**defaults)

    def test_walk_in_needs_no_verification(self):
        job = self._job('WALK_IN')
        self.assertFalse(job.needs_verification)

    def test_remote_order_needs_verification(self):
        job = self._job('WHATSAPP')
        self.assertTrue(job.needs_verification)

    def test_proforma_needs_no_verification(self):
        """
        A quote is built line by line by a manager, agreed with the
        customer and converted deliberately. That is more scrutiny than a
        verification, not less.
        """
        job = self._job('PROFORMA')
        self.assertFalse(job.needs_verification)

    def test_unverified_remote_job_cannot_start_production(self):
        job = self._job('WHATSAPP')
        with self.assertRaises(ValueError):
            JobStatusEngine(job).move_work('IN_PRODUCTION', actor=self.coordinator)

    def test_walk_in_starts_production_without_verification(self):
        job = self._job('WALK_IN')
        JobStatusEngine(job).move_work('IN_PRODUCTION', actor=self.coordinator)
        job.refresh_from_db()
        self.assertEqual(job.work_state, 'IN_PRODUCTION')

    def test_verified_remote_job_starts_production(self):
        job    = self._job('WHATSAPP')
        engine = JobStatusEngine(job)
        engine.verify(actor=self.coordinator, note='Artwork checked, 300dpi.')
        engine.move_work('IN_PRODUCTION', actor=self.coordinator)
        job.refresh_from_db()
        self.assertEqual(job.work_state, 'IN_PRODUCTION')

    def test_rejection_does_not_clear_the_job(self):
        from apps.jobs.models import JobVerification

        job    = self._job('WHATSAPP')
        engine = JobStatusEngine(job)
        engine.reject_verification(
            outcome=JobVerification.Outcome.ARTWORK_PROBLEM,
            actor=self.coordinator,
            note='72dpi, unusable at A3.',
        )
        job.refresh_from_db()
        self.assertFalse(job.is_verified)

    def test_a_job_can_be_rechecked_after_a_rejection(self):
        """
        The customer sends better artwork and it is checked again. Both
        outcomes are kept — a flag would hold only the last one and lose
        why it was ever rejected.
        """
        from apps.jobs.models import JobVerification

        job    = self._job('WHATSAPP')
        engine = JobStatusEngine(job)
        engine.reject_verification(
            outcome=JobVerification.Outcome.ARTWORK_PROBLEM,
            actor=self.coordinator, note='72dpi.',
            customer_contacted=True, customer_response='Will resend.',
        )
        engine.verify(actor=self.coordinator, note='New file is 300dpi.')

        job.refresh_from_db()
        self.assertTrue(job.is_verified)
        self.assertEqual(job.verifications.count(), 2)

    def test_the_customer_call_is_recorded(self):
        from apps.jobs.models import JobVerification

        job = self._job('WHATSAPP')
        JobStatusEngine(job).reject_verification(
            outcome=JobVerification.Outcome.SPEC_UNCLEAR,
            actor=self.coordinator,
            note='Did not say single or double sided.',
            customer_contacted=True,
            customer_response='Double sided, and make it 200 not 100.',
        )
        v = job.verifications.first()
        self.assertTrue(v.customer_contacted)
        self.assertIn('Double sided', v.customer_response)

    def test_attendant_cannot_verify(self):
        job = self._job('WHATSAPP')
        with self.assertRaises(PermissionError):
            JobStatusEngine(job).verify(actor=self.attendant)

    def test_verifying_a_walk_in_is_refused(self):
        job = self._job('WALK_IN')
        with self.assertRaises(ValueError):
            JobStatusEngine(job).verify(actor=self.coordinator)

    def test_verifying_twice_is_refused(self):
        job    = self._job('WHATSAPP')
        engine = JobStatusEngine(job)
        engine.verify(actor=self.coordinator)
        with self.assertRaises(ValueError):
            engine.verify(actor=self.coordinator)