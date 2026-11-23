"""
A trade partner and the people who act for it (23 Nov 2026).

A partner applies on Print Octos, confirms its numbers with a code, and the
owner approves it on his WhatsApp line. Approved, it becomes a business
customer in Octos (the business pays for its jobs; receipts show the
business, never the rep) and gets its ID: the area it is in and a random
code, MAD-K7Q2, shown as MAD·K7Q2.

What we deliberately don't keep: ID card numbers or photos, and the
machines a shop owns (it can feel like prying).
"""
from django.db import models

from apps.core.models import AuditModel


class Partner(AuditModel):

    class Status(models.TextChoices):
        APPLIED = 'APPLIED', 'Applied, waiting for review'
        ASKED = 'ASKED', 'Asked for more'
        APPROVED = 'APPROVED', 'Approved'
        PAUSED = 'PAUSED', 'Paused'
        DECLINED = 'DECLINED', 'Declined'
        CLOSED = 'CLOSED', 'Closed, no answer'
        REMOVED = 'REMOVED', 'Removed'

    class Kind(models.TextChoices):
        PRINT_SHOP = 'PRINT_SHOP', 'Print shop'
        BUSINESS_CENTRE = 'BUSINESS_CENTRE', 'Business centre'
        CYBER_CAFE = 'CYBER_CAFE', 'Cyber café'
        DESIGN_STUDIO = 'DESIGN_STUDIO', 'Design studio'
        OTHER = 'OTHER', 'Other'

    class Volume(models.TextChoices):
        FEW = '1-5', '1 to 5 jobs a month'
        SOME = '6-20', '6 to 20 jobs a month'
        MANY = '20+', 'More than 20 jobs a month'

    # The ID: 'MAD-K7Q2'. Given at approval, never changed or reused.
    code = models.CharField(max_length=12, unique=True, null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.APPLIED, db_index=True)

    # The business.
    name = models.CharField(max_length=120)
    registered_name = models.CharField(max_length=160, blank=True)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    registration_number = models.CharField(max_length=40, blank=True)     # optional, never required
    tin = models.CharField(max_length=30, blank=True)                     # only for VAT invoices
    opening_hours = models.CharField(max_length=120, blank=True)
    shop_photo = models.FileField(upload_to='partners/%Y/%m/', max_length=120)
    logo = models.FileField(upload_to='partners/%Y/%m/', max_length=120)
    logo_approved = models.BooleanField(default=False)                    # for the branded wrap, later

    # Where it is.
    region = models.CharField(max_length=40)
    area = models.CharField(max_length=60)                                 # the town, which gives the ID
    gps_address = models.CharField(max_length=20)                          # Ghana Post, GA-402-1187
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    landmark = models.CharField(max_length=160)

    # How to reach it. The primary contact gets job alerts.
    primary_phone = models.CharField(max_length=20, db_index=True)
    secondary_phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)

    # What it will send us: only services from our own catalogue.
    services = models.ManyToManyField('jobs.Service', related_name='trade_partners', blank=True)
    monthly_volume = models.CharField(max_length=5, choices=Volume.choices)
    heard_from = models.CharField(max_length=120, blank=True)

    # What they agreed to.
    terms_version = models.CharField(max_length=20)
    terms_accepted_at = models.DateTimeField()
    messages_consent = models.BooleanField(default=False)
    invite_code = models.CharField(max_length=40, blank=True)

    # Once approved: the business customer its jobs and receipts belong to.
    customer = models.OneToOneField('customers.CustomerProfile', null=True, blank=True,
                                    on_delete=models.PROTECT, related_name='trade_partner')

    # The review.
    applied_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    asked_at = models.DateTimeField(null=True, blank=True)
    # What the owner asked for, word for word. Blank while Octos waits for him to say it.
    asked_for = models.TextField(blank=True)
    awaiting_question = models.BooleanField(default=False)

    class Meta:
        ordering = ['-applied_at']

    def __str__(self):
        return f'{self.name} ({self.shown_code or self.get_status_display()})'

    @property
    def shown_code(self):
        """MAD·K7Q2, the way it's printed and said."""
        return self.code.replace('-', '·') if self.code else ''

    @property
    def active(self):
        return self.status == self.Status.APPROVED


class PartnerRep(AuditModel):
    """
    A person acting for a partner. Their phone is their sign-in, through the
    same Print Octos account (Lead) a customer has.
    """

    class Role(models.TextChoices):
        OWNER = 'OWNER', 'Owner'
        MANAGER = 'MANAGER', 'Manager'
        STAFF = 'STAFF', 'Staff'

    partner = models.ForeignKey(Partner, on_delete=models.CASCADE, related_name='reps')
    lead = models.ForeignKey('storefront.Lead', on_delete=models.PROTECT, related_name='partner_reps')
    title = models.CharField(max_length=10)
    first_name = models.CharField(max_length=60)
    last_name = models.CharField(max_length=60)
    role = models.CharField(max_length=10, choices=Role.choices)
    is_active = models.BooleanField(default=True)
    # Chosen at registration and kept only as a hash (24 Nov 2026): reps log
    # in with their number and this. A code to the phone sets a new one.
    password = models.CharField(max_length=128, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['partner', 'lead'], name='one_rep_per_person_per_partner')]

    def __str__(self):
        return f'{self.first_name} {self.last_name} for {self.partner.name}'
