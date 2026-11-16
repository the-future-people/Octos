"""
Who is on shift (15 Nov 2026): the Branch Manager's sidebar strip.

Times are pinned (a Monday afternoon in Accra), never read from the
calendar, so the suite passes on any day of the week.
"""
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser, Role
from apps.accounts.on_shift import on_shift
from apps.analytics.models import UserSession
from apps.communications.tests import make_org
from apps.finance.models import AttendantSignOff, CashierFloat, DailySalesSheet
from apps.organization.models import Branch
from apps.production.models import Machine, MachineOperator, MachineType, Station

ACCRA = ZoneInfo('Africa/Accra')
NOW = datetime(2026, 11, 16, 15, 0, tzinfo=ACCRA)


class Base(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_org('-OS')
        cls.other_branch = Branch.objects.create(name='NTB-OS2', code='NTB-OS2', region=cls.branch.region)
        roles = {name: Role.objects.get_or_create(name=name, defaults={
                     'display_name': name.replace('_', ' ').title(), 'is_constrained': False, 'scope': 'BRANCH'})[0]
                 for name in ('ATTENDANT', 'CASHIER', 'BRANCH_MANAGER', 'OPERATOR')}
        cls.roles = roles
        cls.manager = cls.user('OS-BM', roles['BRANCH_MANAGER'], 'Yaw')
        cls.abena = cls.user('OS-ATT-1', roles['ATTENDANT'], 'Abena')
        cls.kojo = cls.user('OS-ATT-2', roles['ATTENDANT'], 'Kojo')
        cls.esi = cls.user('OS-CSH', roles['CASHIER'], 'Esi')
        cls.kwame = cls.user('OS-OP', roles['OPERATOR'], 'Kwame')

    @classmethod
    def user(cls, employee_id, role, name, branch=None):
        u = CustomUser(
            employee_id=employee_id, first_name=name, last_name='Test',
            email=f'{employee_id.lower()}@test.local', employment_status='ACTIVE',
            is_active=True, is_staff=False, is_superuser=False, is_clocked_in=False,
            must_change_password=False, is_business_owner=False, download_pin_set=False,
            branch=branch or cls.branch, role=role,
        )
        u.set_password('test-pass-123')
        u.save()
        return u

    def seen(self, user, minutes_ago, started_minutes_ago=None, ended=False, portal='ATTENDANT'):
        last = NOW - timedelta(minutes=minutes_ago)
        start = NOW - timedelta(minutes=started_minutes_ago or minutes_ago + 60)
        return UserSession.objects.create(
            user=user, branch=user.branch, portal=portal,
            started_at=start, last_seen_at=last, ended_at=last if ended else None,
        )

    def names(self, result):
        return [(s['name'], s['state']) for s in result['staff']]


class StatesTests(Base):

    def test_used_in_the_last_five_minutes_is_active_and_shows_where(self):
        self.seen(self.abena, minutes_ago=2)
        row = on_shift(self.branch, now=NOW)['staff'][0]
        self.assertEqual((row['state'], row['label']), ('active', 'Front desk'))

    def test_quiet_for_longer_is_idle_with_the_minutes(self):
        self.seen(self.kojo, minutes_ago=14)
        row = on_shift(self.branch, now=NOW)['staff'][0]
        self.assertEqual((row['state'], row['label']), ('idle', 'Idle 14m'))

    def test_quiet_for_over_an_hour_says_when_last_seen(self):
        self.seen(self.kojo, minutes_ago=200)   # 11:40am
        row = on_shift(self.branch, now=NOW)['staff'][0]
        self.assertEqual((row['state'], row['label']), ('idle', 'Seen 11:40am'))

    def test_on_break_shows_how_long(self):
        session = self.seen(self.kojo, minutes_ago=20)
        session.on_break_since = NOW - timedelta(minutes=12)
        session.save()
        row = on_shift(self.branch, now=NOW)['staff'][0]
        self.assertEqual((row['state'], row['label']), ('break', 'On break 12m'))

    def test_signed_out_is_off(self):
        self.seen(self.kojo, minutes_ago=30, ended=True)   # 2:30pm
        row = on_shift(self.branch, now=NOW)['staff'][0]
        self.assertEqual((row['state'], row['label']), ('off', 'Signed out 2:30pm'))

    def test_an_attendant_who_signed_off_today_is_off_even_if_still_using_the_portal(self):
        self.seen(self.abena, minutes_ago=1)
        sheet = DailySalesSheet.objects.create(branch=self.branch, date=NOW.date(), status='OPEN')
        AttendantSignOff.objects.create(attendant=self.abena, daily_sheet=sheet,
                                        signed_off_at=NOW - timedelta(minutes=48), signed_off_by=self.abena)
        row = on_shift(self.branch, now=NOW)['staff'][0]
        self.assertEqual((row['state'], row['label']), ('off', 'Off 2:12pm'))

    def test_a_cashier_whose_float_is_signed_off_is_off(self):
        self.seen(self.esi, minutes_ago=3, portal='CASHIER')
        sheet = DailySalesSheet.objects.create(branch=self.branch, date=NOW.date(), status='OPEN')
        CashierFloat.objects.create(daily_sheet=sheet, cashier=self.esi, opening_float=Decimal('100.00'),
                                    is_signed_off=True, signed_off_at=NOW - timedelta(minutes=10))
        self.assertEqual(on_shift(self.branch, now=NOW)['staff'][0]['state'], 'off')

    def test_a_cashier_back_for_a_second_shift_is_on_again(self):
        self.seen(self.esi, minutes_ago=3, portal='CASHIER')
        sheet = DailySalesSheet.objects.create(branch=self.branch, date=NOW.date(), status='OPEN')
        CashierFloat.objects.create(daily_sheet=sheet, cashier=self.esi, opening_float=Decimal('100.00'),
                                    shift_sequence=1, is_signed_off=True, signed_off_at=NOW - timedelta(hours=3))
        CashierFloat.objects.create(daily_sheet=sheet, cashier=self.esi, opening_float=Decimal('100.00'),
                                    shift_sequence=2)
        row = on_shift(self.branch, now=NOW)['staff'][0]
        self.assertEqual((row['state'], row['label']), ('active', 'Till'))

    def test_an_operator_is_named_by_their_machines(self):
        station = Station.objects.create(code='OS-PRINT', name='Printing', sequence=1)
        kind = MachineType.objects.create(code='OS-DTF', name='DTF', station=station)
        for name in ('DTF', 'Heat press'):
            machine = Machine.objects.create(branch=self.branch, machine_type=kind, name=name)
            MachineOperator.objects.create(operator=self.kwame, machine=machine)
        self.seen(self.kwame, minutes_ago=1, portal='OPERATOR')
        self.assertEqual(on_shift(self.branch, now=NOW)['staff'][0]['label'], 'DTF · Heat press')


class WhoCountsTests(Base):

    def test_active_first_then_idle_then_off_and_counts(self):
        self.seen(self.kojo, minutes_ago=20)
        self.seen(self.esi, minutes_ago=40, ended=True, portal='CASHIER')
        self.seen(self.abena, minutes_ago=1)
        result = on_shift(self.branch, now=NOW)
        self.assertEqual(self.names(result), [('Abena', 'active'), ('Kojo', 'idle'), ('Esi', 'off')])
        self.assertEqual((result['on'], result['total']), (2, 3))

    def test_only_people_seen_today(self):
        self.seen(self.kojo, minutes_ago=16 * 60)   # 11pm yesterday
        self.seen(self.abena, minutes_ago=2)
        self.assertEqual(self.names(on_shift(self.branch, now=NOW)), [('Abena', 'active')])

    def test_the_newest_session_decides(self):
        self.seen(self.abena, minutes_ago=90, ended=True)   # closed by a newer one
        self.seen(self.abena, minutes_ago=2)
        result = on_shift(self.branch, now=NOW)
        self.assertEqual(self.names(result), [('Abena', 'active')])

    def test_other_branches_inactive_accounts_and_the_viewer_are_left_out(self):
        stranger = self.user('OS-ATT-X', self.roles['ATTENDANT'], 'Afia', branch=self.other_branch)
        self.seen(stranger, minutes_ago=1)
        gone = self.user('OS-ATT-G', self.roles['ATTENDANT'], 'Gone')
        self.seen(gone, minutes_ago=1)
        gone.is_active = False
        gone.save()
        self.seen(self.manager, minutes_ago=0, portal='BRANCH_MANAGER')
        self.seen(self.abena, minutes_ago=2)
        self.assertEqual(self.names(on_shift(self.branch, now=NOW, viewer=self.manager)), [('Abena', 'active')])

    def test_nobody_in_yet(self):
        self.assertEqual(on_shift(self.branch, now=NOW), {'staff': [], 'on': 0, 'total': 0})


class EndpointTests(Base):

    def get(self, user):
        api = APIClient()
        api.force_authenticate(user)
        return api.get('/api/v1/accounts/on-shift/')

    def test_the_branch_manager_sees_their_branch(self):
        UserSession.objects.create(user=self.abena, branch=self.branch, portal='ATTENDANT',
                                   started_at=timezone.now(), last_seen_at=timezone.now())
        response = self.get(self.manager)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([s['name'] for s in response.data['staff']], ['Abena'])

    def test_staff_at_the_branch_see_it_too(self):
        # Opened to every staff portal on 16 Nov 2026.
        for user in (self.abena, self.esi, self.kwame):
            self.assertEqual(self.get(user).status_code, 200)

    def test_someone_with_no_branch_does_not(self):
        nowhere = CustomUser(employee_id='OS-HQ', first_name='Hq', last_name='Test', email='os-hq@test.local',
                             employment_status='ACTIVE', is_active=True, branch=None, role=self.roles['ATTENDANT'])
        nowhere.set_password('test-pass-123')
        nowhere.save()
        self.assertEqual(self.get(nowhere).status_code, 403)


class PortalTests(Base):

    def test_operators_and_coordinators_can_start_a_session(self):
        api = APIClient()
        api.force_authenticate(self.kwame)
        for portal in ('OPERATOR', 'COORDINATOR'):
            response = api.post('/api/v1/analytics/session/start/', {'portal': portal}, format='json')
            self.assertEqual(response.status_code, 201, portal)
