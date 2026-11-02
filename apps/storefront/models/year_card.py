"""
A customer's year-end thank-you card.

One per customer per year, behind a short private code: the link in the
text opens only that customer's card. The figures are worked out once,
when the card is made, from the customer's own orders, and kept, so the
card a customer opens in January still says what was true in December.

ORDERED: they ordered that year, and the card shows their year.
FAMILY:  they did not (or are new): no figures, only thanks.
"""

from django.db import models


class YearCard(models.Model):
    ORDERED = 'ORDERED'
    FAMILY = 'FAMILY'

    customer = models.ForeignKey('customers.CustomerProfile', on_delete=models.CASCADE,
                                 related_name='year_cards')
    year = models.PositiveSmallIntegerField()
    code = models.CharField(max_length=10, unique=True, db_index=True)
    kind = models.CharField(max_length=10, choices=[(ORDERED, 'Ordered that year'), (FAMILY, 'Thanks only')])
    first_name = models.CharField(max_length=40, blank=True)
    stats = models.JSONField(default=dict, blank=True)

    sent_at = models.DateTimeField(null=True, blank=True)
    opened_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [models.UniqueConstraint(fields=['customer', 'year'], name='one_year_card_per_customer')]

    def __str__(self):
        return f'{self.year} card for {self.customer_id} ({self.kind})'
