"""
Somebody who has ordered online but is not yet a customer.

A first visit asks for a phone number and a first name, nothing more.
Asking a stranger to register before they know what a job costs loses
them, and most first visits never come back — writing every one of them
into CustomerProfile would fill the customer table with people the shop
has met once.

So a first order creates a Lead. When the same number orders again, the
lead has earned a profile, and the second visit is where the surname and
a PIN are asked for. Offered, not forced: a wall at the moment they came
back is the wrong moment.
"""

from django.db import models

from apps.core.models import AuditModel


class Lead(AuditModel):
    phone = models.CharField(max_length=20, unique=True, db_index=True)
    first_name = models.CharField(max_length=100)

    # Set when the lead becomes a real customer. The orders stay attached
    # to the lead; the profile is what the shop deals with afterwards.
    customer = models.OneToOneField(
        'customers.CustomerProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='lead',
        help_text='Set on the visit that turns this lead into a customer.',
    )

    # Protects history, never the job itself. Someone who has just
    # ordered reaches that order by link with no PIN at all — the PIN is
    # what stops a stranger reading everything this number has ever
    # ordered by knowing the number.
    pin = models.CharField(
        max_length=128, blank=True,
        help_text='Hashed. Set when the lead chooses to keep their history.',
    )

    order_count = models.PositiveIntegerField(default=0)
    last_ordered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.first_name} — {self.phone}"

    @property
    def is_returning(self):
        """A second order is what earns a profile."""
        return self.order_count > 0

    @property
    def has_pin(self):
        return bool(self.pin)

    def set_pin(self, raw_pin):
        """Four digits, hashed. Never stored as typed."""
        from django.contrib.auth.hashers import make_password
        self.pin = make_password(raw_pin)

    def check_pin(self, raw_pin):
        from django.contrib.auth.hashers import check_password
        return bool(self.pin) and check_password(raw_pin, self.pin)