"""
The Eye: owner-only, totals that add up, attendance that tells late from
absent, and every lens answering.
"""

from datetime import datetime, time, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser, RFIDAccessLog, Role
from apps.finance.models import DailySalesSheet, Receipt
from apps.hr.models import Employee, EmployeeShift
from apps.organization.models import Belt, Branch, Region

LENSES = ['me', 'tree', 'overview', 'people', 'money', 'jobs', 'machines',
          'inventory', 'customers', 'online', 'app', 'health']


class EyeTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.belt = Belt.objects.create(name='Eye Southern', code='EYS')
        cls.region = Region.objects.create(belt=cls.belt, name='Eye Accra', code='EYA')
        cls.a = Branch.objects.create(region=cls.region, name='Eye Westland', code='EYWL', address='x')
        cls.b = Branch.objects.create(region=cls.region, name='Eye Madina', code='EYMD', address='x')
        cls.owner = CustomUser.objects.create_user(
            email='owner@eye.test', password='x', first_name='Khofi', last_name='Adjei',
            employee_id='EYE-OWNER', is_business_owner=True)
        cls.staffer = CustomUser.objects.create_user(
            email='bm@eye.test', password='x', first_name='Ama', last_name='Mensah',
            employee_id='EYE-BM')
        cls.role = Role.objects.filter(name='ATTENDANT').first() or Role.objects.create(name='ATTENDANT')

    def setUp(self):
        # The Eye keeps answers for 30 seconds; each test asks afresh.
        from django.core.cache import cache
        cache.clear()

    def client_for(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def get(self, lens, **params):
        return self.client_for(self.owner).get(f'/api/v1/eye/{lens}/', params)

    def receipt(self, branch, amount, n):
        sheet, _ = DailySalesSheet.objects.get_or_create(branch=branch, date=timezone.localdate())
        return Receipt.objects.create(
            daily_sheet=sheet, receipt_number=f'RCP-EYE-{n}', sequence=n,
            payment_method='CASH', amount_paid=Decimal(amount))

    # ── Access ───────────────────────────────────────────────

    def test_only_the_owner_gets_in(self):
        resp = self.client_for(self.staffer).get('/api/v1/eye/overview/')
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(APIClient().get('/api/v1/eye/overview/').status_code, 401)

    def test_every_lens_answers(self):
        for lens in LENSES:
            resp = self.get(lens)
            self.assertEqual(resp.status_code, 200, f'{lens}: {getattr(resp, "data", "")}')

    def test_an_unknown_place_is_404(self):
        self.assertEqual(self.get('overview', scope='branch:999999').status_code, 404)
        self.assertEqual(self.get('overview', scope='nonsense').status_code, 404)

    # ── The ladder and true totals ───────────────────────────

    def test_the_ladder_runs_belt_region_branch(self):
        tree = self.get('tree').data
        belt = next(b for b in tree['children'] if b['name'] == 'Eye Southern')
        region = belt['children'][0]
        self.assertEqual(region['name'], 'Eye Accra')
        self.assertEqual({c['name'] for c in region['children']}, {'Eye Westland', 'Eye Madina'})

    def test_totals_add_up_at_every_level(self):
        self.receipt(self.a, '100.00', 1)
        self.receipt(self.b, '50.00', 2)
        region = self.get('overview', scope=f'region:{self.region.pk}').data
        self.assertEqual(region['headline']['revenue'], 150.0)
        self.assertEqual(sum(c['revenue'] for c in region['children']), 150.0)
        branch = self.get('overview', scope=f'branch:{self.a.pk}').data
        self.assertEqual(branch['headline']['revenue'], 100.0)
        self.assertEqual(len(region['dial']), 30)

    def test_a_void_receipt_is_not_revenue(self):
        r = self.receipt(self.a, '80.00', 3)
        Receipt.objects.filter(pk=r.pk).update(is_void=True)
        branch = self.get('overview', scope=f'branch:{self.a.pk}').data
        self.assertEqual(branch['headline']['revenue'], 0.0)

    def test_profit_is_never_guessed(self):
        money = self.get('money', scope=f'branch:{self.a.pk}', period='month').data
        self.assertEqual(money['profit']['state'], 'NOT_TRACKED')

    # ── Attendance ───────────────────────────────────────────

    def _employee(self, email, emp_id):
        u = CustomUser.objects.create_user(
            email=email, password='x', first_name=emp_id, last_name='Test',
            employee_id=emp_id, branch=self.a, role=self.role)
        e = Employee.objects.create(user=u, branch=self.a, role=self.role, base_salary=0)
        return u, e

    def test_late_and_absent_are_told_apart(self):
        day = timezone.localdate() - timedelta(days=1)
        late_u, late_e = self._employee('late@eye.test', 'EYE-L')
        abs_u, abs_e = self._employee('absent@eye.test', 'EYE-A')
        for e in (late_e, abs_e):
            EmployeeShift.objects.create(employee=e, branch=self.a, day_of_week=day.weekday(),
                                         start_time=time(8, 0), end_time=time(17, 0))
        log = RFIDAccessLog.objects.create(employee=late_u, branch=self.a, card_uid='c', action='CLOCK_IN')
        RFIDAccessLog.objects.filter(pk=log.pk).update(
            timestamp=timezone.make_aware(datetime.combine(day, time(8, 25))))

        data = self.get('people', scope=f'branch:{self.a.pk}', day=day.isoformat()).data
        status = {p['id']: p['status'] for p in data['people']}
        self.assertEqual(status[late_u.pk], 'late')
        self.assertEqual(status[abs_u.pk], 'absent')

    def test_leave_is_never_absence(self):
        u, e = self._employee('leave@eye.test', 'EYE-LV')
        today = timezone.localdate()
        EmployeeShift.objects.create(employee=e, branch=self.a, day_of_week=today.weekday(),
                                     start_time=time(0, 1), end_time=time(23, 0))
        Employee.objects.filter(pk=e.pk).update(status='ON_LEAVE')
        data = self.get('people', scope=f'branch:{self.a.pk}').data
        self.assertEqual({p['id']: p['status'] for p in data['people']}[u.pk], 'leave')
