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
from apps.accounts.models import CustomUser, Role
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

    def test_you_may_change_your_phone_but_nothing_else(self):
        response = self.api(self.kofi).patch('/api/v1/accounts/profile/',
                                             {'phone': '024 555 0172', 'first_name': 'Boss', 'employee_id': 'X'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.kofi.refresh_from_db()
        self.assertEqual((self.kofi.phone, self.kofi.first_name, self.kofi.employee_id), ('024 555 0172', 'Kofi', 'PF-ATT'))
        self.notify.assert_not_called()   # nobody is told about their own change

    def test_a_phone_with_letters_is_refused(self):
        response = self.api(self.kofi).patch('/api/v1/accounts/profile/', {'phone': 'call me'}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_a_photo_is_turned_into_a_small_jpeg(self):
        response = self.api(self.kofi).post('/api/v1/accounts/profile/photo/', {'photo': photo_file()}, format='multipart')
        self.assertEqual(response.status_code, 200)
        self.kofi.refresh_from_db()
        with Image.open(self.kofi.photo.path) as saved:
            self.assertEqual(saved.format, 'JPEG')
            self.assertLessEqual(max(saved.size), profiles.PHOTO_SIDE)
        self.assertTrue(response.data['photo_url'])

    def test_a_new_photo_replaces_the_old_file(self):
        client = self.api(self.kofi)
        client.post('/api/v1/accounts/profile/photo/', {'photo': photo_file()}, format='multipart')
        self.kofi.refresh_from_db()
        first = self.kofi.photo.path
        client.post('/api/v1/accounts/profile/photo/', {'photo': photo_file('again.jpg', fmt='JPEG')}, format='multipart')
        self.kofi.refresh_from_db()
        self.assertNotEqual(self.kofi.photo.path, first)
        import os
        self.assertFalse(os.path.exists(first))

    def test_a_file_that_isnt_a_photo_is_refused(self):
        fake = SimpleUploadedFile('notes.png', b'not an image at all', content_type='image/png')
        response = self.api(self.kofi).post('/api/v1/accounts/profile/photo/', {'photo': fake}, format='multipart')
        self.assertEqual(response.status_code, 400)

    def test_removing_your_photo(self):
        client = self.api(self.kofi)
        client.post('/api/v1/accounts/profile/photo/', {'photo': photo_file()}, format='multipart')
        response = client.delete('/api/v1/accounts/profile/photo/')
        self.assertIsNone(response.data['photo_url'])


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
