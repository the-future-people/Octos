from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from apps.hr.api.serializers import PublicVacancySerializer
from apps.hr.models import Applicant

APPLY_URL = '/api/v1/careers/apply/'

# Tests never touch Redis or the R2 bucket
TEST_CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
TEST_STORAGES = {
    'default'    : {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


def _pdf(name='cv.pdf', content=b'%PDF-1.4\n% test cv\n'):
    return SimpleUploadedFile(name, content, content_type='application/pdf')


@override_settings(CACHES=TEST_CACHES, STORAGES=TEST_STORAGES)
class PublicApplyTests(TestCase):
    """The public careers form: what gets in, what gets refused."""

    def setUp(self):
        cache.clear()   # throttle counts live in the cache

    def _payload(self, **overrides):
        data = {
            'first_name': 'Ama',
            'last_name' : 'Mensah',
            'email'     : 'ama@example.com',
            'phone'     : '0244123456',
            'cv'        : _pdf(),
        }
        data.update(overrides)
        return {k: v for k, v in data.items() if v is not None}

    def test_general_application_is_saved_as_website_received_sms(self):
        res = self.client.post(APPLY_URL, self._payload())
        self.assertEqual(res.status_code, 201, res.content)
        a = Applicant.objects.get()
        self.assertEqual(a.track, Applicant.WEBSITE)
        self.assertEqual(a.status, Applicant.RECEIVED)
        self.assertEqual(a.preferred_channel, Applicant.SMS)
        self.assertIsNone(a.vacancy)

    def test_whatsapp_channel_is_refused(self):
        res = self.client.post(APPLY_URL, self._payload(preferred_channel='WHATSAPP'))
        self.assertEqual(res.status_code, 400)
        self.assertIn('preferred_channel', res.json())
        self.assertFalse(Applicant.objects.exists())

    def test_email_channel_is_accepted(self):
        res = self.client.post(APPLY_URL, self._payload(preferred_channel='EMAIL'))
        self.assertEqual(res.status_code, 201, res.content)

    def test_cv_is_required(self):
        res = self.client.post(APPLY_URL, self._payload(cv=None))
        self.assertEqual(res.status_code, 400)
        self.assertIn('cv', res.json())

    def test_wrong_file_type_is_refused(self):
        bad = SimpleUploadedFile('cv.txt', b'hello', content_type='text/plain')
        res = self.client.post(APPLY_URL, self._payload(cv=bad))
        self.assertEqual(res.status_code, 400)
        self.assertIn('cv', res.json())

    def test_renamed_file_is_refused(self):
        fake = _pdf(content=b'MZ\x90\x00 not really a pdf')
        res = self.client.post(APPLY_URL, self._payload(cv=fake))
        self.assertEqual(res.status_code, 400)
        self.assertIn('cv', res.json())

    def test_cv_over_5mb_is_refused(self):
        big = _pdf(content=b'%PDF-' + b'0' * (5 * 1024 * 1024))
        res = self.client.post(APPLY_URL, self._payload(cv=big))
        self.assertEqual(res.status_code, 400)
        self.assertIn('cv', res.json())

    def test_word_cv_is_accepted(self):
        docx = SimpleUploadedFile('cv.docx', b'PK\x03\x04 word body')
        res = self.client.post(APPLY_URL, self._payload(cv=docx))
        self.assertEqual(res.status_code, 201, res.content)

    def test_honeypot_looks_successful_but_saves_nothing(self):
        res = self.client.post(APPLY_URL, self._payload(website='http://spam.example'))
        self.assertEqual(res.status_code, 201)
        self.assertFalse(Applicant.objects.exists())

    def test_sixth_application_in_an_hour_is_throttled(self):
        # Honeypot posts still count against the limit, and store nothing
        for _ in range(5):
            self.assertEqual(
                self.client.post(APPLY_URL, {'website': 'x'}).status_code, 201,
            )
        res = self.client.post(APPLY_URL, self._payload())
        self.assertEqual(res.status_code, 429)
        self.assertFalse(Applicant.objects.exists())


class PublicVacancyContractTests(TestCase):
    """What the public vacancy payload may and may not expose."""

    def test_private_fields_are_not_public(self):
        fields = PublicVacancySerializer.Meta.fields
        self.assertNotIn('applicant_count', fields)
        self.assertNotIn('base_salary', fields)

    def test_careers_page_fields_are_public(self):
        fields = PublicVacancySerializer.Meta.fields
        for f in ('team', 'team_label', 'responsibilities', 'requirements',
                  'pay_text', 'working_hours', 'benefits',
                  'positions_available', 'employment_type', 'closes_at'):
            self.assertIn(f, fields)