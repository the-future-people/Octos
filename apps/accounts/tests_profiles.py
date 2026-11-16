"""
Staff profiles (15 Nov 2026): photos, phones, who may change them, and each
role's numbers.

Times are pinned to a Wednesday in Accra, never read from the calendar.
Photos are written to a throwaway folder.
"""
import io
import shutil
import tempfile
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image
from rest_framework.test import APIClient

from apps.accounts import profiles
from apps.accounts.models import CustomUser, ProfileChange, Role
from apps.communications.tests import make_org
from apps.finance.models import AttendantSignOff, CashierFloat, DailySalesSheet, Receipt
from apps.jobs.models import Job, JobLineItem, JobStatusLog, JobStep, Service
from apps.organization.models import Branch
from apps.production.models import Machine, MachineOperator, MachineType, Station

ACCRA = ZoneInfo('Africa/Accra')
WEDNESDAY = datetime(2026, 11, 18, 15, 0, tzinfo=ACCRA)
MEDIA = tempfile.mkdtemp()


def photo_file(name='me.png', size=(1200, 900), fmt='PNG'):
    buffer = io.BytesIO()
    Image.new('RGB', size, (200, 30, 30)).save(buffer, format=fmt)
    return SimpleUploadedFile(name, buffer.getvalue(), content_type=f'image/{fmt.lower()}')


@override_settings(MEDIA_ROOT=MEDIA, STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class Base(TestCase):

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_org('-PF')
        cls.other = Branch.objects.create(name='NTB-PF2', code='NTB-PF2', region=cls.branch.region)
        roles = {name: Role.objects.get_or_create(name=name, defaults={
                     'display_name': name.replace('_', ' ').title(), 'is_constrained': False, 'scope': 'BRANCH'})[0]
                 for name in ('ATTENDANT', 'CASHIER', 'BRANCH_MANAGER', 'OPERATOR', 'FLOW_COORDINATOR', 'OCTOS')}
        cls.roles = roles
        cls.manager = cls.user('PF-BM', 'BRANCH_MANAGER', 'Yaw')
        cls.kofi = cls.user('PF-ATT', 'ATTENDANT', 'Kofi')
        cls.ama = cls.user('PF-CSH', 'CASHIER', 'Ama')
        cls.steve = cls.user('PF-OP', 'OPERATOR', 'Steve')
        cls.stranger = cls.user('PF-X', 'ATTENDANT', 'Afia', branch=cls.other)
        cls.banner = Service.objects.create(name='PF Banner', code='PF-BAN', category=Service.PRODUCTION)

    @classmethod
    def user(cls, employee_id, role, name, branch=None):
        u = CustomUser(
            employee_id=employee_id, first_name=name, last_name='Test', email=f'{employee_id.lower()}@test.local',
            employment_status='ACTIVE', is_active=True, branch=branch or cls.branch, role=cls.roles[role],
        )
        u.set_password('test-pass-123')
        u.save()
        return u

    def api(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def setUp(self):
        notify = patch('apps.notifications.services.notify')
        self.notify = notify.start()
        self.addCleanup(notify.stop)


class OwnProfileTests(Base):

    def test_your_own_card(self):
        data = self.api(self.kofi).get('/api/v1/accounts/profile/').data
        self.assertEqual((data['full_name'], data['role_label'], data['employee_id']), ('Kofi Test', 'Attendant', 'PF-ATT'))
        self.assertEqual([n['label'] for n in data['numbers']], ['Jobs recorded', 'Front desk done', 'Signed off themselves'])
        self.assertIsNone(data['photo_url'])
        self.assertEqual(data['pending'], [])
        self.assertFalse(data['approves_own'])

    def test_a_new_phone_waits_for_the_branch_manager(self):
        response = self.api(self.kofi).patch('/api/v1/accounts/profile/',
                                             {'phone': '024 555 0172', 'first_name': 'Boss', 'employee_id': 'X'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.kofi.refresh_from_db()
        self.assertEqual((self.kofi.phone, self.kofi.first_name, self.kofi.employee_id), ('', 'Kofi', 'PF-ATT'))
        self.assertEqual([(p['field'], p['value']) for p in response.data['pending']], [('PHONE', '024 555 0172')])
        # The Branch Manager is asked, with a link to the Staff page.
        self.assertEqual(self.notify.call_args.kwargs['recipient'], self.manager)
        self.assertIn('asked to change their phone number to 024 555 0172', self.notify.call_args.kwargs['message'])
        self.assertEqual(self.notify.call_args.kwargs['link'], '/bm/staff/')

    def test_a_new_email_waits_too(self):
        self.api(self.kofi).patch('/api/v1/accounts/profile/', {'email': 'Kofi.New@Farhat.com'}, format='json')
        self.kofi.refresh_from_db()
        self.assertEqual(self.kofi.email, 'pf-att@test.local')
        self.assertEqual(ProfileChange.objects.get(user=self.kofi).new_value, 'kofi.new@farhat.com')

    def test_an_email_someone_else_uses_is_refused(self):
        response = self.api(self.kofi).patch('/api/v1/accounts/profile/', {'email': 'PF-CSH@test.local'}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_asking_again_replaces_the_request_still_waiting(self):
        client = self.api(self.kofi)
        client.patch('/api/v1/accounts/profile/', {'phone': '0241111111'}, format='json')
        client.patch('/api/v1/accounts/profile/', {'phone': '0242222222'}, format='json')
        self.assertEqual(list(ProfileChange.objects.filter(user=self.kofi, status='PENDING')
                              .values_list('new_value', flat=True)), ['0242222222'])

    def test_taking_back_a_request(self):
        client = self.api(self.kofi)
        pending = client.patch('/api/v1/accounts/profile/', {'phone': '0241111111'}, format='json').data['pending'][0]
        response = client.delete(f"/api/v1/accounts/profile/changes/{pending['id']}/")
        self.assertEqual(response.data['pending'], [])

    def test_a_phone_with_letters_is_refused(self):
        response = self.api(self.kofi).patch('/api/v1/accounts/profile/', {'phone': 'call me'}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_a_new_photo_waits_as_a_small_jpeg(self):
        response = self.api(self.kofi).post('/api/v1/accounts/profile/photo/', {'photo': photo_file()}, format='multipart')
        self.assertEqual(response.status_code, 200)
        self.kofi.refresh_from_db()
        self.assertFalse(self.kofi.photo)
        change = ProfileChange.objects.get(user=self.kofi)
        with Image.open(change.new_photo.path) as waiting:
            self.assertEqual(waiting.format, 'JPEG')
            self.assertLessEqual(max(waiting.size), profiles.PHOTO_SIDE)
        self.assertTrue(response.data['pending'][0]['photo_url'])

    def test_a_file_that_isnt_a_photo_is_refused(self):
        fake = SimpleUploadedFile('notes.png', b'not an image at all', content_type='image/png')
        response = self.api(self.kofi).post('/api/v1/accounts/profile/photo/', {'photo': fake}, format='multipart')
        self.assertEqual(response.status_code, 400)

    def test_the_branch_managers_own_changes_apply_at_once(self):
        client = self.api(self.manager)
        client.patch('/api/v1/accounts/profile/', {'phone': '0559999999'}, format='json')
        data = client.post('/api/v1/accounts/profile/photo/', {'photo': photo_file()}, format='multipart').data
        self.manager.refresh_from_db()
        self.assertEqual(self.manager.phone, '0559999999')
        self.assertTrue(self.manager.photo)
        self.assertEqual(data['pending'], [])
        self.notify.assert_not_called()


class ApprovalTests(Base):

    def ask_phone(self, phone='024 555 0172'):
        return self.api(self.kofi).patch('/api/v1/accounts/profile/', {'phone': phone}, format='json').data['pending'][0]['id']

    def decide(self, change_id, decision, user=None, note=''):
        return self.api(user or self.manager).post(f'/api/v1/accounts/staff/changes/{change_id}/{decision}/',
                                                    {'note': note}, format='json')

    def test_the_staff_page_lists_what_is_waiting(self):
        self.ask_phone()
        waiting = self.api(self.manager).get('/api/v1/accounts/staff/').data['waiting']
        self.assertEqual([(w['first_name'], w['field'], w['value'], w['current']) for w in waiting],
                         [('Kofi', 'PHONE', '024 555 0172', '')])

    def test_approving_applies_it_and_tells_them(self):
        change_id = self.ask_phone()
        self.assertEqual(self.decide(change_id, 'approve').status_code, 200)
        self.kofi.refresh_from_db()
        self.assertEqual(self.kofi.phone, '024 555 0172')
        self.assertEqual(self.notify.call_args.kwargs['recipient'], self.kofi)
        self.assertEqual(self.notify.call_args.kwargs['message'], 'Yaw Test approved your new phone.')

    def test_an_approved_email_becomes_the_sign_in(self):
        self.api(self.kofi).patch('/api/v1/accounts/profile/', {'email': 'kofi@farhat.com'}, format='json')
        self.decide(ProfileChange.objects.get(user=self.kofi).pk, 'approve')
        self.kofi.refresh_from_db()
        self.assertEqual(self.kofi.email, 'kofi@farhat.com')
        self.assertIn('Sign in with it from now on.', self.notify.call_args.kwargs['message'])

    def test_an_approved_photo_becomes_theirs_and_the_waiting_copy_goes(self):
        self.api(self.kofi).post('/api/v1/accounts/profile/photo/', {'photo': photo_file()}, format='multipart')
        change = ProfileChange.objects.get(user=self.kofi)
        waiting = change.new_photo.path
        self.decide(change.pk, 'approve')
        self.kofi.refresh_from_db()
        self.assertTrue(self.kofi.photo)
        import os
        self.assertFalse(os.path.exists(waiting))

    def test_rejecting_leaves_it_and_says_why(self):
        change_id = self.ask_phone()
        self.decide(change_id, 'reject', note='That is not your number')
        self.kofi.refresh_from_db()
        self.assertEqual(self.kofi.phone, '')
        self.assertEqual(self.notify.call_args.kwargs['message'],
                         "Yaw Test didn't approve your new phone number: That is not your number")

    def test_a_request_is_decided_once(self):
        change_id = self.ask_phone()
        self.decide(change_id, 'approve')
        self.assertEqual(self.decide(change_id, 'reject').status_code, 400)

    def test_only_the_branch_manager_of_their_branch_decides(self):
        change_id = self.ask_phone()
        self.assertEqual(self.decide(change_id, 'approve', user=self.ama).status_code, 403)
        other_bm = self.user('PF-BM2', 'BRANCH_MANAGER', 'Efua', branch=self.other)
        self.assertEqual(self.decide(change_id, 'approve', user=other_bm).status_code, 400)

    def test_an_email_taken_while_waiting_is_refused_at_approval(self):
        self.api(self.kofi).patch('/api/v1/accounts/profile/', {'email': 'shared@farhat.com'}, format='json')
        self.ama.email = 'shared@farhat.com'
        self.ama.save()
        response = self.decide(ProfileChange.objects.get(user=self.kofi).pk, 'approve')
        self.assertEqual(response.status_code, 400)


class ManagerTests(Base):

    def test_the_manager_sees_every_role_at_his_branch_only(self):
        data = self.api(self.manager).get('/api/v1/accounts/staff/').data
        names = [c['first_name'] for c in data['staff']]
        self.assertEqual(names, ['Yaw', 'Ama', 'Kofi', 'Steve'])   # manager, cashier, attendant, operator
        self.assertEqual(data['counts'], {'Branch Manager': 1, 'Cashier': 1, 'Attendant': 1, 'Operator': 1})

    def test_the_octos_account_is_not_staff(self):
        octos = self.user('PF-OCTOS', 'OCTOS', 'Octos')
        octos.is_active = False
        octos.save()
        names = [c['first_name'] for c in self.api(self.manager).get('/api/v1/accounts/staff/').data['staff']]
        self.assertNotIn('Octos', names)

    def test_nobody_else_sees_the_staff_list(self):
        self.assertEqual(self.api(self.kofi).get('/api/v1/accounts/staff/').status_code, 403)

    def test_the_manager_changes_a_photo_and_the_person_is_told(self):
        response = self.api(self.manager).post(f'/api/v1/accounts/staff/{self.kofi.pk}/photo/',
                                               {'photo': photo_file()}, format='multipart')
        self.assertEqual(response.status_code, 200)
        self.notify.assert_called_once()
        self.assertEqual(self.notify.call_args.kwargs['recipient'], self.kofi)
        self.assertEqual(self.notify.call_args.kwargs['message'], 'Yaw Test updated your photo.')

    def test_the_manager_changes_a_phone_and_the_person_is_told(self):
        response = self.api(self.manager).patch(f'/api/v1/accounts/staff/{self.ama.pk}/', {'phone': '0201234567'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.ama.refresh_from_db()
        self.assertEqual(self.ama.phone, '0201234567')
        self.assertEqual(self.notify.call_args.kwargs['message'], 'Yaw Test updated your phone number.')

    def test_the_manager_changes_an_email_and_they_are_told_to_sign_in_with_it(self):
        response = self.api(self.manager).patch(f'/api/v1/accounts/staff/{self.ama.pk}/', {'email': 'ama@farhat.com'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.ama.refresh_from_db()
        self.assertEqual(self.ama.email, 'ama@farhat.com')
        self.assertIn('Sign in with it from now on.', self.notify.call_args.kwargs['message'])

    def test_not_someone_at_another_branch(self):
        response = self.api(self.manager).patch(f'/api/v1/accounts/staff/{self.stranger.pk}/', {'phone': '0201234567'}, format='json')
        self.assertEqual(response.status_code, 404)

    def test_an_attendant_cannot_change_someone_else(self):
        response = self.api(self.kofi).patch(f'/api/v1/accounts/staff/{self.ama.pk}/', {'phone': '0201234567'}, format='json')
        self.assertEqual(response.status_code, 403)


class NumbersTests(Base):

    def values(self, user, period='week'):
        return {n['label']: n['value'] for n in profiles.numbers(user, period, now=WEDNESDAY)}

    def job(self, **kwargs):
        defaults = dict(branch=self.branch, job_type=Job.PRODUCTION, title='Banner', status=Job.PAID,
                        estimated_cost=Decimal('40.00'))
        defaults.update(kwargs)
        job = Job.objects.create(**defaults)
        return job

    def at(self, obj, field, when):
        type(obj).objects.filter(pk=obj.pk).update(**{field: when})

    def test_week_starts_on_monday_and_month_on_the_first(self):
        self.assertEqual(profiles.period_start('week', WEDNESDAY).date().isoformat(), '2026-11-16')
        self.assertEqual(profiles.period_start('month', WEDNESDAY).date().isoformat(), '2026-11-01')
        self.assertEqual(profiles.period_start('today', WEDNESDAY).date().isoformat(), '2026-11-18')

    def test_attendant(self):
        for days_ago in (0, 1, 5):    # Wednesday, Tuesday, last Friday
            job = self.job(intake_by=self.kofi)
            self.at(job, 'created_at', WEDNESDAY - timedelta(days=days_ago))
        desk = self.job(front_desk=True)
        JobStatusLog.objects.create(job=desk, axis=JobStatusLog.Axis.WORK, from_status='IN_PRODUCTION',
                                    to_status='DONE', actor=self.kofi, transitioned_at=WEDNESDAY - timedelta(hours=2))
        sheet = DailySalesSheet.objects.create(branch=self.branch, date=WEDNESDAY.date(), status='OPEN')
        AttendantSignOff.objects.create(attendant=self.kofi, daily_sheet=sheet, signed_off_by=self.kofi,
                                        signed_off_at=WEDNESDAY - timedelta(hours=1))
        self.assertEqual(self.values(self.kofi), {'Jobs recorded': '2', 'Front desk done': '1', 'Signed off themselves': '1/1'})
        self.assertEqual(self.values(self.kofi, 'today')['Jobs recorded'], '1')
        self.assertEqual(self.values(self.kofi, 'month')['Jobs recorded'], '3')

    def test_cashier(self):
        sheet = DailySalesSheet.objects.create(branch=self.branch, date=WEDNESDAY.date(), status='OPEN')
        for shift, variance in ((1, '0.00'), (2, '-5.00')):
            CashierFloat.objects.create(daily_sheet=sheet, cashier=self.ama, opening_float=Decimal('100.00'),
                                        shift_sequence=shift,
                                        is_signed_off=True, variance=Decimal(variance),
                                        signed_off_at=WEDNESDAY - timedelta(hours=3))
        job = self.job()
        self.at(job, 'created_at', WEDNESDAY - timedelta(minutes=10))
        receipt = Receipt.objects.create(job=job, cashier=self.ama, daily_sheet=sheet, amount_paid=Decimal('40.00'),
                                         receipt_number='RCP-PF-1', sequence=1, payment_method='CASH')
        self.at(receipt, 'created_at', WEDNESDAY - timedelta(minutes=4))
        self.assertEqual(self.values(self.ama), {'Receipts': '1', 'Drawer exact': '1/2', 'Avg wait to pay': '6m'})

    def test_operator(self):
        station = Station.objects.create(code='PF-PRINT', name='Printing', sequence=1)
        kind = MachineType.objects.create(code='PF-DTF', name='DTF', station=station)
        machine = Machine.objects.create(branch=self.branch, machine_type=kind, name='DTF')
        MachineOperator.objects.create(operator=self.steve, machine=machine)
        job = self.job()
        line = JobLineItem.objects.create(job=job, service=self.banner, quantity=1, unit_price=Decimal('40.00'),
                                          line_total=Decimal('40.00'), position=0)
        JobStep.objects.create(job=job, line_item=line, station=station, sequence=1, machine=machine,
                               state=JobStep.State.DONE, expected_minutes=Decimal('90'),
                               done_by=self.steve, done_at=WEDNESDAY - timedelta(hours=1))
        self.assertEqual(self.values(self.steve), {'Steps done': '1', 'Machine work': '1h 30m', 'Machines': '1'})

    def test_manager(self):
        self.assertEqual(list(self.values(self.manager)), ['Chats handled', 'Approvals', 'Hours active'])
        job = self.job(post_closing=True, post_closing_reason='late customer', post_closing_approved_by=self.manager)
        self.at(job, 'created_at', WEDNESDAY - timedelta(hours=1))
        self.assertEqual(self.values(self.manager)['Approvals'], '1')

    def test_nothing_yet_reads_as_a_dash_not_zero_of_zero(self):
        self.assertEqual(self.values(self.kofi)['Signed off themselves'], '—')
