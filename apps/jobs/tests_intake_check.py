"""
The intake check: ordered vs file, the gate before Clear, and what the
floor is told. Built on the 30 Oct 2026 case: a 6 x 6 in banner ordered,
a 40 x 40 in file sent.
"""

from decimal import Decimal

from django.test import TestCase

from apps.jobs.models import Job, JobFile, JobLineItem, Service
from apps.jobs.services.intake_check import compare, gate, operator_notes
from apps.jobs.tests import JobsFixtureMixin


class IntakeCheckTests(JobsFixtureMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.banner = Service.objects.create(
            name='Flexy Banner', code='ICBAN', category='PRODUCTION', unit='PER_SQFT',
            requires_design=False, requires_file_upload=True, is_active=True,
        )
        cls.flyer = Service.objects.create(
            name='Flyers', code='ICFLY', category='PRODUCTION', unit='PER_SHEET',
            requires_design=False, requires_file_upload=True, is_active=True,
        )

    def _job(self, service, specs=None, paper='A4', file_mm=(1016, 1016), file_px=(8000, 8000)):
        job = Job.objects.create(
            branch=self.branch, job_type='PRODUCTION', status=Job.PAID, title='Intake test',
            intake_by=self.bm, estimated_cost=Decimal('60.00'), daily_sheet=self.sheet,
        )
        line = JobLineItem.objects.create(
            job=job, service=service, quantity=1, pages=1, paper_size=paper,
            specifications=specs or {},
        )
        if file_mm:
            JobFile.objects.create(
                job=job, line_item=line, file='jobs/t/art.jpg', file_type='ORIGINAL',
                metadata_state='MEASURED', content_type='image/jpeg', colour_mode='RGB',
                width_mm=Decimal(str(file_mm[0])), height_mm=Decimal(str(file_mm[1])),
                width_px=file_px[0], height_px=file_px[1],
            )
        return job, line

    def _rows(self, job):
        return {r['key']: r for r in compare(job)['pieces'][0]['rows']}

    # ── The comparison ───────────────────────────────────────

    def test_the_real_case_size_is_amber_and_can_be_scaled(self):
        job, _ = self._job(self.banner, {'width_in': '6', 'height_in': '6'})
        rows = self._rows(job)
        self.assertEqual(rows['SIZE']['status'], 'warn')
        self.assertEqual((rows['SIZE']['ordered'], rows['SIZE']['file']), ('6 × 6 in', '40 × 40 in'))
        self.assertEqual(rows['SIZE']['fixes'], ['SCALE'])
        self.assertEqual(rows['RESOLUTION']['status'], 'ok')
        self.assertEqual(rows['RESOLUTION']['file'], '1,333 dpi')
        self.assertEqual(rows['QUANTITY']['status'], 'ok')
        self.assertEqual(rows['EDGES']['status'], 'sign')

    def test_a_different_shape_cannot_be_scaled_only_held(self):
        job, _ = self._job(self.banner, {'width_in': '6', 'height_in': '6'}, file_mm=(1016, 508))
        self.assertEqual(self._rows(job)['SIZE']['fixes'], [])

    def test_sheet_work_without_bleed_is_amber_and_with_bleed_is_fine(self):
        bare, _ = self._job(self.flyer, file_mm=(210, 297), file_px=(2480, 3508))
        self.assertEqual(self._rows(bare)['BLEED']['status'], 'warn')
        bled, _ = self._job(self.flyer, file_mm=(216, 303), file_px=(2551, 3579))
        self.assertEqual(self._rows(bled)['BLEED']['status'], 'ok')
        self.assertEqual(self._rows(bled)['SIZE']['status'], 'ok')

    # ── The gate ─────────────────────────────────────────────

    def test_nothing_clears_unsettled_and_unsigned(self):
        job, _ = self._job(self.banner, {'width_in': '6', 'height_in': '6'})
        missing = gate(job, [], {})
        self.assertEqual(len(missing), 3)
        self.assertIn('read the text', missing)
        self.assertIn('check the edges', missing)

    def test_settled_and_signed_it_clears(self):
        job, line = self._job(self.banner, {'width_in': '6', 'height_in': '6'})
        self.assertEqual(gate(job, ['TEXT', 'EDGES'], {f'{line.pk}:SIZE': 'SCALE'}), [])

    def test_a_settlement_the_row_does_not_offer_is_refused(self):
        job, line = self._job(self.banner, {'width_in': '6', 'height_in': '6'})
        self.assertEqual(len(gate(job, ['TEXT', 'EDGES'], {f'{line.pk}:SIZE': 'NO_BLEED'})), 1)

    def test_the_floor_is_told_to_scale(self):
        job, line = self._job(self.banner, {'width_in': '6', 'height_in': '6'})
        notes = operator_notes(job, {f'{line.pk}:SIZE': 'SCALE'})
        self.assertEqual(notes, ['Flexy Banner: print at 6 × 6 in (file is 40 × 40 in, scale it).'])

    # ── The API ──────────────────────────────────────────────

    def _client(self):
        from rest_framework.test import APIClient
        client = APIClient()
        client.force_authenticate(user=self.coordinator)
        return client

    def test_api_intake_check_returns_the_rows_and_a_signed_file_link(self):
        job, _ = self._job(self.banner, {'width_in': '6', 'height_in': '6'})
        resp = self._client().get(f'/api/v1/jobs/{job.pk}/intake-check/')
        self.assertEqual(resp.status_code, 200, resp.data)
        piece = resp.data['pieces'][0]
        self.assertTrue(piece['file']['url'].startswith(f"/api/v1/jobs/files/{piece['file']['id']}/?t="))
        self.assertEqual(resp.data['job']['job_number'], job.job_number)

    def test_a_letter_document_ordered_as_a4_can_be_fitted(self):
        """31 Oct 2026: a Word CV in Letter size was left with only Hold."""
        printing = Service.objects.create(
            name='A4 B&W Printing', code='ICDOC', category='PRODUCTION', unit='PER_PAGE',
            requires_design=False, requires_file_upload=True, is_active=True,
        )
        job, _ = self._job(printing, paper='A4', file_mm=(215.9, 279.4), file_px=None or (0, 0))
        rows = self._rows(job)
        self.assertEqual(rows['SIZE']['fixes'], ['FIT'])
        self.assertEqual(rows['BLEED']['status'], 'ok')

    def test_a_72_dpi_poster_warns_and_can_be_checked_by_eye(self):
        """31 Oct 2026: a 21 x 15 in poster at 72 dpi was refused outright."""
        job, _ = self._job(self.banner, {'width_in': '21', 'height_in': '15'},
                           file_mm=(533.4, 381.0), file_px=(1491, 1055))
        row = self._rows(job)['RESOLUTION']
        self.assertEqual(row['status'], 'warn')
        self.assertEqual(row['fixes'], ['CHECKED'])

    def test_counter_production_work_can_be_cleared(self):
        """30 Oct 2026: shown for inspection, then refused as 'needs no verification'."""
        from apps.jobs.status_engine import JobStatusEngine
        job, _ = self._job(self.banner, {'width_in': '6', 'height_in': '6'})
        Job.objects.filter(pk=job.pk).update(intake_channel='WALK_IN', work_state='RECEIVED')
        job.refresh_from_db()
        JobStatusEngine(job).verify(actor=self.coordinator)
        job.refresh_from_db()
        self.assertTrue(job.is_verified)

    def test_counter_instant_work_still_needs_no_verification(self):
        from apps.jobs.status_engine import JobStatusEngine
        job, _ = self._job(self.banner, {'width_in': '6', 'height_in': '6'})
        Job.objects.filter(pk=job.pk).update(intake_channel='WALK_IN', job_type='INSTANT')
        job.refresh_from_db()
        with self.assertRaises(ValueError):
            JobStatusEngine(job).verify(actor=self.coordinator)

    def test_api_clear_is_refused_until_settled_and_signed(self):
        job, _ = self._job(self.banner, {'width_in': '6', 'height_in': '6'})
        resp = self._client().post(f'/api/v1/jobs/{job.pk}/verify/', {}, format='json')
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertEqual(len(resp.data['missing']), 3)