"""
Changing a service's photo from the catalogue pane (17 Nov 2026).

Photos are kept in memory here, never sent to the bucket.
"""
import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser, Role
from apps.communications.tests import make_org
from apps.jobs.models import Service

IN_MEMORY = {
    'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


def photo(name='binding.png', kind='image/png', size=(40, 30)):
    buffer = io.BytesIO()
    Image.new('RGB', size, (200, 30, 30)).save(buffer, format='PNG')
    return SimpleUploadedFile(name, buffer.getvalue(), content_type=kind)


@override_settings(STORAGES=IN_MEMORY)
class ServicePhotoTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_org('-SP')
        roles = {name: Role.objects.get_or_create(name=name, defaults={
                     'display_name': name.title(), 'is_constrained': False, 'scope': 'BRANCH'})[0]
                 for name in ('BRANCH_MANAGER', 'ATTENDANT')}
        cls.manager = cls.user('SP-BM', roles['BRANCH_MANAGER'])
        cls.attendant = cls.user('SP-ATT', roles['ATTENDANT'])
        cls.service = Service.objects.create(code='SP-BIND', name='A3 Binding', category='INSTANT',
                                             unit='PER_PIECE', is_active=True)

    @classmethod
    def user(cls, employee_id, role):
        u = CustomUser(employee_id=employee_id, first_name='Test', last_name='User',
                       email=f'{employee_id.lower()}@test.local', employment_status='ACTIVE',
                       is_active=True, branch=cls.branch, role=role)
        u.set_password('test-pass-123')
        u.save()
        return u

    def api(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def url(self):
        return f'/api/v1/jobs/services/{self.service.pk}/photo/'

    def test_a_manager_sets_a_photo_and_the_list_shows_it(self):
        response = self.api(self.manager).put(self.url(), {'image': photo()}, format='multipart')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['image'])
        listed = self.api(self.manager).get('/api/v1/jobs/services/').data
        self.assertTrue(next(s for s in listed if s['id'] == self.service.pk)['image'])

    def test_a_new_photo_replaces_the_old_one_in_storage(self):
        self.api(self.manager).put(self.url(), {'image': photo('first.png')}, format='multipart')
        self.service.refresh_from_db()
        first = self.service.image.name
        storage = self.service.image.storage
        self.api(self.manager).put(self.url(), {'image': photo('second.png')}, format='multipart')
        self.service.refresh_from_db()
        self.assertNotEqual(self.service.image.name, first)
        self.assertFalse(storage.exists(first))

    def test_taking_the_photo_off(self):
        self.api(self.manager).put(self.url(), {'image': photo()}, format='multipart')
        response = self.api(self.manager).delete(self.url())
        self.assertEqual(response.status_code, 200)
        self.service.refresh_from_db()
        self.assertFalse(self.service.image)

    def test_an_attendant_cannot(self):
        response = self.api(self.attendant).put(self.url(), {'image': photo()}, format='multipart')
        self.assertEqual(response.status_code, 403)

    def test_only_photos(self):
        pdf = SimpleUploadedFile('menu.pdf', b'%PDF-1.4', content_type='application/pdf')
        response = self.api(self.manager).put(self.url(), {'image': pdf}, format='multipart')
        self.assertEqual(response.status_code, 400)

    def test_nothing_chosen(self):
        response = self.api(self.manager).put(self.url(), {}, format='multipart')
        self.assertEqual(response.status_code, 400)
