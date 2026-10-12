"""
A paid order becoming work the floor can see.

Everything before this is the customer's side: a cart, a price, a
payment. This is where it crosses into the shop — a job on the board, a
receipt in the books, artwork the press can open.

It is the last gap in the chain. Until it exists, money arrives and
nobody at Farhat hears about it.
"""

import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.customers.models import CustomerProfile
from apps.finance.models import DailySalesSheet, Receipt
from apps.jobs.models import Job, PricingRule, Service
from apps.organization.models import Branch
from apps.storefront.models import Lead, OnlineOrder, OrderFile


class ConversionTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = Branch.objects.create(
            name='Convert Branch', code='CVB',
            is_headquarters=False, is_regional_hq=False,
            address='1 Convert Road',
            capacity_score=100, current_load=0, is_active=True,
            opening_time=datetime.time(7, 30), closing_time=datetime.time(19, 30),
            vat_registered=False, vat_rate=Decimal('0'),
            nhil_rate=Decimal('0'), getfund_rate=Decimal('0'),
        )

        cls.flexy = Service.objects.create(
            name='Convert Flexy', code='CVFLEXY',
            category='PRODUCTION', unit='PER_SQFT',
            requires_file_upload=True, is_active=True,
        )
        PricingRule.objects.create(
            service=cls.flexy, branch=None, base_price=Decimal('3.25'),
            color_multiplier=Decimal('1.00'), minimum_price=Decimal('10.00'),
            is_active=True,
        )

    def _sheet(self, status=None):
        sheet, _ = DailySalesSheet.objects.get_or_create(
            branch=self.branch, date=timezone.localdate(),
            defaults={'status': DailySalesSheet.Status.OPEN},
        )
        if status:
            sheet.status = status
            sheet.save(update_fields=['status'])
        return sheet

    def _order(self, phone='0244800100', name='Abena', **overrides):
        lead = Lead.objects.create(phone=phone, first_name=name)
        order = OnlineOrder.objects.create(
            lead=lead, branch=self.branch,
            line_items=[{
                'id': 'line-one',
                'service': self.flexy.id,
                'service_name': self.flexy.name,
                'quantity': 2,
                'specifications': {'width_in': 72, 'height_in': 36},
                'unit_price': '58.50',
                'total': '117.00',
            }],
            full_total=Decimal('117.00'), total=Decimal('117.00'),
            status=OnlineOrder.Status.PAID,
            paid_at=timezone.now(),
            payment_reference='CVT-001',
            payment_fee=Decimal('2.28'),
            net_received=Decimal('114.72'),
            **overrides,
        )
        return order

    def _with_artwork(self, order):
        import io
        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile

        buf = io.BytesIO()
        Image.new('RGB', (9000, 4500), (20, 60, 140)).save(buf, 'JPEG')
        buf.seek(0)

        return OrderFile.objects.create(
            order=order, line_id='line-one',
            file=SimpleUploadedFile('banner.jpg', buf.read(),
                                    content_type='image/jpeg'),
            original_filename='banner.jpg',
            verdict='fine', width_px=9000, height_px=4500,
        )

    # ── A job on the board ─────────────────────────────────────────

    def test_a_paid_order_becomes_a_job(self):
        from apps.storefront.services.conversion import convert

        self._sheet()
        order = self._order()

        job = convert(order)

        self.assertIsNotNone(job)
        self.assertEqual(job.branch_id, self.branch.pk)
        self.assertEqual(job.estimated_cost, Decimal('117.00'))

    def test_the_job_starts_where_the_floor_expects(self):
        """
        Paid in full, received, waiting to be collected. Not a deposit
        and not in production — nobody has touched it yet.
        """
        from apps.storefront.services.conversion import convert

        self._sheet()
        job = convert(self._order())

        self.assertEqual(job.payment_state, 'PAID')
        self.assertEqual(job.work_state, 'RECEIVED')
        self.assertEqual(job.handover_state, 'AWAITING_COLLECTION')

    def test_nobody_took_it_in(self):
        """
        An online order has no attendant. The field stays empty rather
        than naming an invented member of staff — a fake row in a real
        table travels further than anyone expects.
        """
        from apps.storefront.services.conversion import convert

        self._sheet()
        job = convert(self._order())
        self.assertIsNone(job.intake_by_id)

    def test_the_lines_carry_over(self):
        from apps.storefront.services.conversion import convert

        self._sheet()
        job = convert(self._order())

        lines = list(job.line_items.all())
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0].service_id, self.flexy.pk)
        self.assertEqual(lines[0].quantity, 2)
        self.assertEqual(lines[0].specifications['width_in'], 72)

    def test_the_order_knows_its_job(self):
        from apps.storefront.services.conversion import convert

        self._sheet()
        order = self._order()
        job = convert(order)

        order.refresh_from_db()
        self.assertEqual(order.job_id, job.pk)
        self.assertEqual(order.status, OnlineOrder.Status.CONVERTED)

    # ── The customer ───────────────────────────────────────────────

    def test_a_new_number_becomes_a_customer(self):
        from apps.storefront.services.conversion import convert

        self._sheet()
        job = convert(self._order(phone='0244800999', name='Yaw'))

        self.assertIsNotNone(job.customer_id)
        self.assertEqual(job.customer.phone, '0244800999')

    def test_a_number_we_know_is_not_duplicated(self):
        """
        Somebody who has walked in before is the same person online.
        Two records of them is how a customer's history splits in half.
        """
        from apps.storefront.services.conversion import convert

        existing = CustomerProfile.objects.create(
            first_name='Kofi', last_name='Mensah', phone='0244800100',
            customer_type='INDIVIDUAL', branch=self.branch,
        )

        self._sheet()
        job = convert(self._order(phone='0244800100'))

        self.assertEqual(job.customer_id, existing.pk)
        self.assertEqual(
            CustomerProfile.objects.filter(phone='0244800100').count(), 1,
        )

    # ── The artwork ────────────────────────────────────────────────

    def test_the_artwork_follows_the_job(self):
        from apps.storefront.services.conversion import convert

        self._sheet()
        order = self._order()
        self._with_artwork(order)

        job = convert(order)

        files = list(job.files.all())
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].original_filename, 'banner.jpg')
        self.assertEqual(files[0].width_px, 9000)

    def test_the_verdict_follows_too(self):
        """
        The coordinator should see what the customer was told. A file
        accepted with a warning is not the same as one that passed.
        """
        from apps.storefront.services.conversion import convert

        self._sheet()
        order = self._order()
        record = self._with_artwork(order)
        record.verdict = 'warn'
        record.save(update_fields=['verdict'])

        job = convert(order)
        self.assertEqual(job.files.first().verdict, 'warn')

    # ── The money ──────────────────────────────────────────────────

    def test_a_receipt_is_written(self):
        from apps.storefront.services.conversion import convert

        sheet = self._sheet()
        job = convert(self._order())

        receipt = Receipt.objects.get(job=job)
        self.assertEqual(receipt.amount_paid, Decimal('117.00'))
        self.assertEqual(receipt.payment_method, 'ONLINE')
        self.assertEqual(receipt.daily_sheet_id, sheet.pk)
        self.assertEqual(receipt.balance_due, Decimal('0.00'))

    def test_the_receipt_carries_the_customer(self):
        from apps.storefront.services.conversion import convert

        self._sheet()
        job = convert(self._order(name='Abena'))

        receipt = Receipt.objects.get(job=job)
        self.assertIn('Abena', receipt.customer_name)
        self.assertEqual(receipt.customer_phone, '0244800100')

    def test_nobody_took_the_money_either(self):
        from apps.storefront.services.conversion import convert

        self._sheet()
        job = convert(self._order())
        self.assertIsNone(Receipt.objects.get(job=job).cashier_id)

    # ── While the branch is shut ───────────────────────────────────

    def test_with_no_open_sheet_the_receipt_waits(self):
        """
        Paid at twenty to midnight on a Sunday. The job is real and the
        floor should see it in the morning, but the money cannot land
        on a sheet that does not exist.
        """
        from apps.storefront.services.conversion import convert

        job = convert(self._order())

        self.assertIsNotNone(job)
        self.assertIsNone(job.daily_sheet_id)
        self.assertIsNone(Receipt.objects.get(job=job).daily_sheet_id)

    def test_a_closed_sheet_is_never_written_to(self):
        """
        The manager counted the drawer and signed it off. A total that
        moves afterwards is worse than money that arrives late.
        """
        from apps.storefront.services.conversion import convert

        self._sheet(status=DailySalesSheet.Status.CLOSED)
        job = convert(self._order())

        self.assertIsNone(job.daily_sheet_id)
        self.assertIsNone(Receipt.objects.get(job=job).daily_sheet_id)

    def test_waiting_money_lands_when_a_sheet_opens(self):
        from apps.storefront.services.conversion import convert, catch_up

        job = convert(self._order())
        self.assertIsNone(job.daily_sheet_id)

        sheet = self._sheet()
        self.assertEqual(catch_up(self.branch), 1)

        job.refresh_from_db()
        self.assertEqual(job.daily_sheet_id, sheet.pk)
        self.assertEqual(
            Receipt.objects.get(job=job).daily_sheet_id, sheet.pk,
        )

    def test_catching_up_twice_changes_nothing(self):
        from apps.storefront.services.conversion import convert, catch_up

        convert(self._order())
        self._sheet()

        self.assertEqual(catch_up(self.branch), 1)
        self.assertEqual(catch_up(self.branch), 0)

    # ── Doing it twice ─────────────────────────────────────────────

    def test_an_order_is_only_converted_once(self):
        """
        Paystack retries, and the sweep runs behind the task. Two jobs
        for one payment means the floor prints a banner twice.
        """
        from apps.storefront.services.conversion import convert

        self._sheet()
        order = self._order()

        first = convert(order)
        second = convert(order)

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Job.objects.filter(branch=self.branch).count(), 1)
        self.assertEqual(Receipt.objects.filter(job=first).count(), 1)

    def test_an_unpaid_order_is_refused(self):
        from apps.storefront.services.conversion import convert

        self._sheet()
        order = self._order()
        order.status = OnlineOrder.Status.AWAITING_PAYMENT
        order.paid_at = None
        order.save()

        self.assertIsNone(convert(order))
        self.assertEqual(Job.objects.filter(branch=self.branch).count(), 0)

    def test_an_order_with_no_branch_is_refused(self):
        from apps.storefront.services.conversion import convert

        self._sheet()
        order = self._order()
        order.branch = None
        order.save()

        self.assertIsNone(convert(order))

    # ── The promise ────────────────────────────────────────────────

    def test_the_promise_is_recorded_on_the_job(self):
        """
        What the customer was told, frozen. Recomputing it later would
        make it agree with whatever the queue says then, and the
        question worth answering is whether we kept our word.
        """
        from apps.storefront.services.conversion import convert

        self._sheet()
        order = self._order(promised_for=timezone.now() + timezone.timedelta(hours=4))
        job = convert(order)

        self.assertIsNotNone(job.estimated_ready_at)