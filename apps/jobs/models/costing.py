"""
What things cost, and prices lowered by hand (17 Nov 2026).

CostSettings: the toner, paper and machine wear behind a printed page, set
once by the Branch Manager or the owner. From them Octos works out what a
page costs (services/costing.py), and so what a job costs.

PriceCut: a price lowered on a proforma or a job, with its reason and who
gave it. The Branch Manager may lower a price while the job still earns
floor_multiple times its cost; below that the owner decides (PENDING until
then). The proforma's or job's own total is what changes, so every screen
that reads the price is right without knowing discounts exist.
"""
from decimal import Decimal

from django.conf import settings
from django.db import models

from apps.core.models import AuditModel


class CostSettings(AuditModel):
    """One row for the company: what a page is made of."""

    toner_black_price  = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('775'))
    toner_black_pages  = models.PositiveIntegerField(default=36000, help_text='Pages a black toner prints (Canon rates it at 5% cover).')
    toner_colour_price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('775'))
    toner_colour_pages = models.PositiveIntegerField(default=19000, help_text='Pages each colour toner prints at 5% cover.')
    paper_box_price    = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('350'))
    paper_box_sheets   = models.PositiveIntegerField(default=2500, help_text='Sheets in a box: 5 reams of 500.')
    coverage           = models.DecimalField(
        max_digits=4, decimal_places=1, default=Decimal('3.0'),
        help_text='How much more toner a typical page uses than the 5% the yields assume: 3 for charts and pictures.')
    wear_percent       = models.DecimalField(
        max_digits=5, decimal_places=1, default=Decimal('30.0'),
        help_text='Drum, fuser, servicing and power, as a share of paper and toner.')
    floor_multiple     = models.DecimalField(
        max_digits=4, decimal_places=1, default=Decimal('2.5'),
        help_text='The Branch Manager may lower a price while the job earns this many times its cost.')
    unknown_cost_limit = models.DecimalField(
        max_digits=4, decimal_places=1, default=Decimal('10.0'),
        help_text='When a job holds something with no cost set, the most the Branch Manager may take off, in percent.')

    class Meta:
        verbose_name = 'cost settings'
        verbose_name_plural = 'cost settings'

    @classmethod
    def current(cls):
        row = cls.objects.order_by('pk').first()
        return row or cls.objects.create()


class PriceCut(AuditModel):
    """A price lowered on a proforma or a job: applied, or waiting for the owner."""

    class Status(models.TextChoices):
        APPLIED  = 'APPLIED',  'Applied'
        PENDING  = 'PENDING',  'Waiting for the owner'
        DECLINED = 'DECLINED', 'Not approved'
        REPLACED = 'REPLACED', 'Replaced by a newer one'

    job       = models.ForeignKey('jobs.Job', null=True, blank=True, on_delete=models.CASCADE, related_name='price_cuts')
    proforma  = models.ForeignKey('jobs.ProformaInvoice', null=True, blank=True, on_delete=models.CASCADE,
                                  related_name='price_cuts')
    before_total = models.DecimalField(max_digits=10, decimal_places=2, help_text='The price before this cut (after any bulk price).')
    new_total    = models.DecimalField(max_digits=10, decimal_places=2)
    amount       = models.DecimalField(max_digits=10, decimal_places=2)
    reason       = models.CharField(max_length=300)
    cost         = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True,
                                       help_text='What the work cost to make, when every part of it has a cost.')
    floor_total  = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    status       = models.CharField(max_length=10, choices=Status.choices, db_index=True)
    asked_by     = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='price_cuts_asked')
    decided_by   = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name='price_cuts_decided')
    decided_at   = models.DateTimeField(null=True, blank=True)
    note         = models.CharField(max_length=300, blank=True, help_text="The owner's reason, when he says no.")

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.CheckConstraint(condition=models.Q(job__isnull=False) | models.Q(proforma__isnull=False),
                                   name='price_cut_has_a_target'),
        ]

    @property
    def percent(self):
        return (self.amount / self.before_total * 100).quantize(Decimal('0.1')) if self.before_total else Decimal('0')
