"""
The year-end card: each customer's year, worked out from their own
orders, and only what is true for them.

  orders      jobs placed that year (cancelled, voided and drafts left out)
  favourite   the service on most of those jobs' lines
  first       the month of their first order that year
  biggest     their busiest month, only when it held at least two orders

A customer with no orders that year gets the FAMILY card: no figures.
"""

import secrets
from collections import Counter
from datetime import date

from django.conf import settings
from django.db.models.functions import TruncMonth

from apps.storefront.services.welcome import business_name, first_name

KIND_PREFIX = 'yearcard'
MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
          'August', 'September', 'October', 'November', 'December']
DEAD = ('DRAFT', 'CANCELLED', 'VOIDED')
ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'


def text_kind(year):
    return f'{KIND_PREFIX}-{year}'


def year_of(customer, year):
    from apps.jobs.models import Job, JobLineItem

    jobs = (Job.objects.filter(customer=customer, created_at__year=year)
            .exclude(status__in=DEAD))
    n = jobs.count()
    if not n:
        return None

    names = Counter(JobLineItem.objects.filter(job__in=jobs)
                    .values_list('service__name', flat=True))
    names.pop(None, None)
    favourite = names.most_common(1)[0][0] if names else ''

    first_at = jobs.order_by('created_at').values_list('created_at', flat=True).first()
    per_month = Counter(m.month for m in jobs.annotate(m=TruncMonth('created_at')).values_list('m', flat=True) if m)
    month, count = per_month.most_common(1)[0]
    return {
        'orders': n,
        'favourite': _short(favourite),
        'first_month': MONTHS[first_at.month - 1] if first_at else '',
        'biggest_month': MONTHS[month - 1] if count >= 2 else '',
        'biggest_count': count if count >= 2 else 0,
    }


def _short(name):
    """'Flexy Banner 6ft' reads as 'Flexy Banner' on a tile."""
    words = (name or '').split()
    return ' '.join(words[:2])


def _code():
    from apps.storefront.models import YearCard
    for _ in range(10):
        c = ''.join(secrets.choice(ALPHABET) for _ in range(8))
        if not YearCard.objects.filter(code=c).exists():
            return c
    raise RuntimeError('Could not mint a card code')


def card_for(customer, year):
    """The customer's card for the year, made once and kept."""
    from apps.storefront.models import YearCard

    card = YearCard.objects.filter(customer=customer, year=year).first()
    if card:
        return card
    stats = year_of(customer, year)
    return YearCard.objects.create(
        customer=customer, year=year, code=_code(),
        kind=YearCard.ORDERED if stats else YearCard.FAMILY,
        first_name=first_name(customer), stats=stats or {},
    )


def host():
    return getattr(settings, 'STOREFRONT_HOST', 'print-octos.vercel.app')


def card_text(card) -> str:
    """One SMS, plain ASCII, under 160 characters."""
    hello = f'Hi {card.first_name}, thank' if card.first_name else 'Thank'
    text = (f'{hello} you for being with {business_name()} in {card.year}! '
            f'We made you a little thank-you card: {host()}/y/{card.code} Afehyia pa!')
    if len(text) > 160:
        text = (f'Thank you for being with {business_name()} in {card.year}! '
                f'Your thank-you card: {host()}/y/{card.code} Afehyia pa!')
    return text


def card_page(card) -> dict:
    """What the card page needs, and nothing about anyone else."""
    return {
        'year': card.year,
        'next_year': card.year + 1,
        'kind': card.kind,
        'first_name': card.first_name,
        'business': business_name(),
        'stats': card.stats,
    }


def recipients():
    """Everyone registered with a number worth texting."""
    from apps.customers.models import CustomerProfile
    from apps.storefront.services.sms import _normalise
    seen = set()
    for c in CustomerProfile.objects.filter(is_walkin=False).exclude(phone='').order_by('created_at'):
        number = _normalise(c.phone)
        if number and number not in seen:
            seen.add(number)
            yield c, number
