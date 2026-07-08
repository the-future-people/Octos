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