"""
Who an app account is: the customer behind the number.

Signing in proves a number; this says who holds it. A number the counter
already knows is the counter's customer, so Eric Nortey, a regular since
before the app, is welcomed back rather than signed up again. A number
nobody knows yet is asked, once, for a short registration, which makes
a proper customer the counter recognises from the first visit.

POST account/register/ (App token)
    { kind: PERSONAL | BUSINESS, title, gender, first_name, last_name,
      business_name?, address? }

Completes the customer behind the number, or makes one: never a second.
"""

from django.db import transaction
from django.db.models import Q
from rest_framework import status
from rest_framework.response import Response

TITLES = {'MR', 'MRS', 'MS', 'DR', 'PROF', 'OTHER'}
GENDERS = {'MALE', 'FEMALE'}
ORG_TYPES = ('BUSINESS', 'INSTITUTION')


def customer_for(lead):
    """The customer behind this lead: linked already, or found by any of their numbers (and linked)."""
    from apps.core.phones import lookup_forms
    from apps.customers.models import CustomerProfile

    if lead.customer_id:
        return lead.customer
    forms = lookup_forms(lead.phone)
    found = (CustomerProfile.objects
             .filter(Q(phone__in=forms) | Q(secondary_phone__in=forms))
             .order_by('created_at').first())
    if found is not None:
        lead.customer = found
        lead.save(update_fields=['customer'])
    return found


def profile_for(lead):
    """What the app shows and whether the short registration is still needed."""
    c = customer_for(lead)
    if c is None:
        return {'complete': False, 'kind': None}
    business = c.customer_type in ORG_TYPES
    complete = bool(c.first_name and c.last_name and c.title and (
        (c.company_name and c.address) if business else c.gender))
    return {
        'complete': complete,
        'kind': 'BUSINESS' if business else 'PERSONAL',
        'title': c.title or '',
        'first_name': c.first_name or '',
        'last_name': c.last_name or '',
        'gender': c.gender or '',
        'business_name': c.company_name or '' if business else '',
        'address': c.address or '' if business else '',
    }


def register(lead, data):
    """Complete the customer behind the number, or make one. Returns problems, or None."""
    from apps.customers.models import CustomerProfile
    from apps.customers.utils import normalise_phone

    kind = (data.get('kind') or 'PERSONAL').upper()
    title = (data.get('title') or '').upper()
    gender = (data.get('gender') or '').upper()
    first = (data.get('first_name') or '').strip()[:100]
    last = (data.get('last_name') or '').strip()[:100]
    business = (data.get('business_name') or '').strip()[:200]
    address = (data.get('address') or '').strip()[:300]

    if kind not in ('PERSONAL', 'BUSINESS'):
        return 'Choose personal or business.'
    if title not in TITLES:
        return 'Choose a title.'
    if not first or not last:
        return 'Tell us your first and last name.'
    if kind == 'PERSONAL' and gender not in GENDERS:
        return 'Choose male or female.'
    if kind == 'BUSINESS' and (not business or not address):
        return 'Tell us the business’s name and where it is.'

    with transaction.atomic():
        c = customer_for(lead)
        if c is None:
            c = CustomerProfile(phone=normalise_phone(lead.phone),
                                customer_type='BUSINESS' if kind == 'BUSINESS' else 'INDIVIDUAL')
        elif kind == 'BUSINESS' and c.customer_type not in ORG_TYPES:
            # A known person registering a business on their own number:
            # the counter links people to businesses; the app keeps them
            # as the person they already are.
            return ('This number is already registered to you personally. '
                    'To order for a business, choose it at the counter, or use the business’s own number.')
        c.title = title
        c.first_name = first
        c.last_name = last
        if kind == 'PERSONAL':
            c.gender = gender
        else:
            c.company_name = business
            c.address = address
        c.save()
        lead.customer = c
        lead.first_name = first
        lead.save(update_fields=['customer', 'first_name'])
    return None


def register_view(view, request):
    session = view.session(request)
    if session is None:
        return view.refused()
    problem = register(session.lead, request.data)
    if problem:
        return Response({'detail': problem}, status=status.HTTP_400_BAD_REQUEST)
    from apps.storefront.account_views import _account
    return Response(_account(session.lead))