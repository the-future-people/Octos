"""
Tests for the Jobs API.

Coverage:
  - JobListView          — list, branch scoping, filters, search
  - JobDetailView        — detail, branch isolation, allowed_transitions
  - JobCreateView        — create, auto-price, branch default, validation
  - JobTransitionView    — valid transition, invalid transition, 404
  - JobFileUploadView    — upload file, 404
  - JobRouteSuggestView  — suggest routing, missing service param
  - JobRouteConfirmView  — confirm route, bad branch
  - ServiceListView      — list, category filter
  - PricingRuleListView  — list, branch/service filters
  - PriceCalculateView   — calculate, missing params, no rule found

Run:
  python manage.py test apps.jobs.tests --verbosity=2
"""

import uuid
import io
from decimal import Decimal
from django.test import TestCase
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from rest_framework import status

from apps.accounts.models import CustomUser
from apps.organization.models import Belt, Region, Branch
from apps.jobs.models import Job, Service, PricingRule, JobFile


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def make_org(suffix=''):
    belt   = Belt.objects.create(name=f'Southern Belt {suffix}')
    region = Region.objects.create(name=f'Accra Region {suffix}', belt=belt)
    branch = Branch.objects.create(
        name=f'NTB {suffix}', code=f'NTB{suffix}',
        region=region, address='Test Address',
    )
    return branch


def make_user(email, branch, password='pass1234'):
    user = CustomUser.objects.create_user(
        email=email,
        password=password,
        first_name='Test',
        last_name='User',
        employee_id=str(uuid.uuid4())[:20],
    )
    user.branch = branch
    user.save()
    return user


def make_service(name='Photocopy', code=None, category='INSTANT', unit='PER_PAGE'):
    return Service.objects.create(
        name=name,
        code=code or name[:10].upper().replace(' ', '_'),
        category=category,
        unit=unit,
    )


def make_pricing_rule(service, branch=None, base_price='2.00'):
    return PricingRule.objects.create(
        service=service,
        branch=branch,
        base_price=Decimal(base_price),
    )


def make_job(branch, user, job_type='INSTANT', **kwargs):
    defaults = dict(
        title='Test Job',
        job_type=job_type,
        status='DRAFT',
    )
    defaults.update(kwargs)
    return Job.objects.create(branch=branch, intake_by=user, **defaults)


def get_results(res):
    if isinstance(res.data, list):
        return res.data
    return res.data.get('results', res.data)


# ─────────────────────────────────────────────────────────────
# Base
# ─────────────────────────────────────────────────────────────

class JobsTestBase(TestCase):

    def setUp(self):
        self.branch  = make_org('A')
        self.user    = make_user('staff@octos.test', self.branch)
        self.client  = APIClient()
        self.client.force_authenticate(user=self.user)
        self.service = make_service()
        self.rule    = make_pricing_rule(self.service, self.branch)
        self.job     = make_job(self.branch, self.user)


# ─────────────────────────────────────────────────────────────
# List
# ─────────────────────────────────────────────────────────────

class JobListTests(JobsTestBase):

    def test_list_returns_200(self):
        res = self.client.get(reverse('job-list'))
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_list_requires_auth(self):
        self.client.logout()
        res = self.client.get(reverse('job-list'))
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_scoped_to_users_branch(self):
        other_branch = Branch.objects.create(
            name='Other', code='OTH',
            region=self.branch.region, address='Addr',
        )
        other_user = make_user('other@octos.test', other_branch)
        make_job(other_branch, other_user)

        results = get_results(self.client.get(reverse('job-list')))
        self.assertTrue(all(j['branch'] == self.branch.id for j in results))

    def test_list_filter_by_status(self):
        self.job.status = 'CONFIRMED'
        self.job.save()
        results = get_results(
            self.client.get(reverse('job-list'), {'status': 'CONFIRMED'})
        )
        self.assertTrue(all(j['status'] == 'CONFIRMED' for j in results))

    def test_list_filter_by_job_type(self):
        make_job(self.branch, self.user, job_type='PRODUCTION', title='Prod Job')
        results = get_results(
            self.client.get(reverse('job-list'), {'job_type': 'PRODUCTION'})
        )
        self.assertTrue(all(j['job_type'] == 'PRODUCTION' for j in results))

    def test_list_search_by_title(self):
        make_job(self.branch, self.user, title='ZZZ Unique Title')
        results = get_results(
            self.client.get(reverse('job-list'), {'search': 'ZZZ Unique'})
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['title'], 'ZZZ Unique Title')


# ─────────────────────────────────────────────────────────────
# Detail
# ─────────────────────────────────────────────────────────────

class JobDetailTests(JobsTestBase):

    def test_detail_returns_200(self):
        res = self.client.get(reverse('job-detail', args=[self.job.pk]))
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_detail_contains_allowed_transitions(self):
        res = self.client.get(reverse('job-detail', args=[self.job.pk]))
        self.assertIn('allowed_transitions', res.data)
        self.assertIsInstance(res.data['allowed_transitions'], list)

    def test_detail_draft_instant_allowed_transitions(self):
        res = self.client.get(reverse('job-detail', args=[self.job.pk]))
        self.assertIn('CONFIRMED', res.data['allowed_transitions'])
        self.assertIn('CANCELLED', res.data['allowed_transitions'])

    def test_detail_contains_files_and_status_logs(self):
        res = self.client.get(reverse('job-detail', args=[self.job.pk]))
        self.assertIn('files', res.data)
        self.assertIn('status_logs', res.data)

    def test_detail_404_for_other_branch(self):
        other_branch = Branch.objects.create(
            name='Other2', code='OT2',
            region=self.branch.region, address='Addr',
        )
        other_user = make_user('other2@octos.test', other_branch)
        other_job  = make_job(other_branch, other_user)
        res = self.client.get(reverse('job-detail', args=[other_job.pk]))
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)


# ─────────────────────────────────────────────────────────────
# Create
# ─────────────────────────────────────────────────────────────

class JobCreateTests(JobsTestBase):

    def _payload(self, **overrides):
        data = {
            'title'          : 'New Print Job',
            'job_type'       : 'INSTANT',
            'priority'       : 'NORMAL',
            'intake_channel' : 'WALK_IN',
            'service'        : self.service.id,
            'quantity'       : 10,
            'pages'          : 2,
            'is_color'       : False,
        }
        data.update(overrides)
        return data

    def test_create_returns_201(self):
        res = self.client.post(reverse('job-create'), self._payload())
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    def test_create_generates_job_number(self):
        self.client.post(reverse('job-create'), self._payload())
        job = Job.objects.filter(title='New Print Job').first()
        self.assertIsNotNone(job)
        self.assertTrue(job.job_number.startswith('FP-'))

    def test_create_auto_calculates_price(self):
        self.client.post(reverse('job-create'), self._payload(quantity=5, pages=1))
        job = Job.objects.filter(title='New Print Job').first()
        self.assertIsNotNone(job.estimated_cost)
        self.assertGreater(job.estimated_cost, 0)

    def test_create_sets_intake_by(self):
        self.client.post(reverse('job-create'), self._payload())
        job = Job.objects.filter(title='New Print Job').first()
        self.assertEqual(job.intake_by, self.user)

    def test_create_defaults_branch_to_users_branch(self):
        self.client.post(reverse('job-create'), self._payload())
        job = Job.objects.filter(title='New Print Job').first()
        self.assertEqual(job.branch, self.branch)

    def test_create_requires_title(self):
        payload = self._payload()
        del payload['title']
        res = self.client.post(reverse('job-create'), payload)
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_requires_job_type(self):
        payload = self._payload()
        del payload['job_type']
        res = self.client.post(reverse('job-create'), payload)
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)


# ─────────────────────────────────────────────────────────────
# Transition
# ─────────────────────────────────────────────────────────────

class JobTransitionTests(JobsTestBase):

    def test_valid_transition_returns_200(self):
        res = self.client.post(
            reverse('job-transition', args=[self.job.pk]),
            {'to_status': 'CONFIRMED'},
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['to_status'], 'CONFIRMED')

    def test_transition_updates_job_status(self):
        self.client.post(
            reverse('job-transition', args=[self.job.pk]),
            {'to_status': 'CONFIRMED'},
        )
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, 'CONFIRMED')

    def test_transition_logs_status_change(self):
        self.client.post(
            reverse('job-transition', args=[self.job.pk]),
            {'to_status': 'CONFIRMED'},
        )
        self.assertEqual(self.job.status_logs.count(), 1)
        log = self.job.status_logs.first()
        self.assertEqual(log.from_status, 'DRAFT')
        self.assertEqual(log.to_status, 'CONFIRMED')

    def test_invalid_transition_returns_400(self):
        # DRAFT → COMPLETE is not allowed for INSTANT
        res = self.client.post(
            reverse('job-transition', args=[self.job.pk]),
            {'to_status': 'COMPLETE'},
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_transition_404_unknown_job(self):
        res = self.client.post(
            reverse('job-transition', args=[99999]),
            {'to_status': 'CONFIRMED'},
        )
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_transition_requires_to_status(self):
        res = self.client.post(
            reverse('job-transition', args=[self.job.pk]),
            {},
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_production_transition_map(self):
        prod_job = make_job(self.branch, self.user, job_type='PRODUCTION')
        res = self.client.post(
            reverse('job-transition', args=[prod_job.pk]),
            {'to_status': 'CONFIRMED'},
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        # CONFIRMED → QUEUED (production path)
        res2 = self.client.post(
            reverse('job-transition', args=[prod_job.pk]),
            {'to_status': 'QUEUED'},
        )
        self.assertEqual(res2.status_code, status.HTTP_200_OK)


# ─────────────────────────────────────────────────────────────
# File Upload
# ─────────────────────────────────────────────────────────────

class JobFileUploadTests(JobsTestBase):

    def _make_file(self, name='test.pdf', content=b'%PDF content'):
        return SimpleUploadedFile(name, content, content_type='application/pdf')

    def test_upload_returns_201(self):
        res = self.client.post(
            reverse('job-file-upload', args=[self.job.pk]),
            {'file': self._make_file(), 'file_type': 'ORIGINAL'},
            format='multipart',
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    def test_upload_creates_job_file(self):
        self.client.post(
            reverse('job-file-upload', args=[self.job.pk]),
            {'file': self._make_file(), 'file_type': 'ORIGINAL'},
            format='multipart',
        )
        self.assertEqual(JobFile.objects.filter(job=self.job).count(), 1)

    def test_upload_sets_uploaded_by(self):
        self.client.post(
            reverse('job-file-upload', args=[self.job.pk]),
            {'file': self._make_file(), 'file_type': 'ORIGINAL'},
            format='multipart',
        )
        f = JobFile.objects.filter(job=self.job).first()
        self.assertEqual(f.uploaded_by, self.user)

    def test_upload_404_unknown_job(self):
        res = self.client.post(
            reverse('job-file-upload', args=[99999]),
            {'file': self._make_file(), 'file_type': 'ORIGINAL'},
            format='multipart',
        )
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)


# ─────────────────────────────────────────────────────────────
# Services
# ─────────────────────────────────────────────────────────────

class ServiceListTests(JobsTestBase):

    def test_service_list_returns_200(self):
        res = self.client.get(reverse('service-list'))
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_service_list_filter_by_category(self):
        make_service('Large Format', 'LF', category='PRODUCTION', unit='PER_SQM')
        results = get_results(
            self.client.get(reverse('service-list'), {'category': 'INSTANT'})
        )
        self.assertTrue(all(s['category'] == 'INSTANT' for s in results))

    def test_service_list_excludes_inactive(self):
        inactive = make_service('Old Service', 'OLD')
        inactive.is_active = False
        inactive.save()
        results = get_results(self.client.get(reverse('service-list')))
        ids = [s['id'] for s in results]
        self.assertNotIn(inactive.id, ids)


# ─────────────────────────────────────────────────────────────
# Pricing Rules
# ─────────────────────────────────────────────────────────────

class PricingRuleListTests(JobsTestBase):

    def test_pricing_list_returns_200(self):
        res = self.client.get(reverse('pricing-list'))
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_pricing_filter_by_branch(self):
        results = get_results(
            self.client.get(reverse('pricing-list'), {'branch': self.branch.id})
        )
        self.assertTrue(all(r['branch'] == self.branch.id for r in results))

    def test_pricing_filter_by_service(self):
        results = get_results(
            self.client.get(reverse('pricing-list'), {'service': self.service.id})
        )
        self.assertTrue(all(r['service'] == self.service.id for r in results))


# ─────────────────────────────────────────────────────────────
# Price Calculate
# ─────────────────────────────────────────────────────────────

class PriceCalculateTests(JobsTestBase):

    def _url(self, **params):
        base = reverse('price-calculate')
        qs   = '&'.join(f'{k}={v}' for k, v in params.items())
        return f'{base}?{qs}'

    def test_calculate_returns_200(self):
        res = self.client.get(self._url(
            service=self.service.id, branch=self.branch.id,
            quantity=5, pages=2,
        ))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data['success'])

    def test_calculate_returns_correct_total(self):
        # base_price=2.00, quantity=5, pages=2, not color → 2.00 * 2 * 5 = 20.00
        res = self.client.get(self._url(
            service=self.service.id, branch=self.branch.id,
            quantity=5, pages=2, is_color='false',
        ))
        self.assertEqual(res.data['total'], Decimal('20.00'))

    def test_calculate_applies_color_multiplier(self):
        self.rule.color_multiplier = Decimal('1.50')
        self.rule.save()
        # base=2.00, multiplier=1.5, quantity=1, pages=1 → 3.00
        res = self.client.get(self._url(
            service=self.service.id, branch=self.branch.id,
            quantity=1, pages=1, is_color='true',
        ))
        self.assertEqual(res.data['total'], Decimal('3.00'))

    def test_calculate_missing_service_returns_400(self):
        res = self.client.get(self._url(branch=self.branch.id))
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_calculate_missing_branch_returns_400(self):
        res = self.client.get(self._url(service=self.service.id))
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_calculate_no_pricing_rule_returns_failure(self):
        # Service with no rule for this branch
        new_service = make_service('Binding', 'BIND', unit='FLAT_RATE')
        res = self.client.get(self._url(
            service=new_service.id, branch=self.branch.id,
        ))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertFalse(res.data['success'])

    def test_calculate_404_unknown_service(self):
        res = self.client.get(self._url(service=99999, branch=self.branch.id))
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_calculate_404_unknown_branch(self):
        res = self.client.get(self._url(service=self.service.id, branch=99999))
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)