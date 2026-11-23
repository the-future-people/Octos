"""
Applying to be a trade partner (23 Nov 2026).

1. The shop asks for a code on its primary contact and on the rep's phone
   (the same six-digit code app sign-in uses).
2. It sends the application with both codes, its photo and logo.
3. Octos checks it isn't already a partner or a copy of another shop, finds
   its history as a Farhat customer, and puts it in front of the owner on
   his line (review.py).

Sign-ups stay closed until PARTNER_SIGNUPS_OPEN; until then only a shop with
an invite code can apply.
"""
import re

from django.conf import settings
from django.db import transaction
from django.utils import timezone

TERMS_VERSION = '2026-11-23'
MAX_IMAGE = 8 * 1024 * 1024
IMAGE_TYPES = {'image/jpeg', 'image/png', 'image/webp', 'image/heic', 'image/heif'}
LOGO_TYPES = IMAGE_TYPES | {'application/pdf', 'image/svg+xml'}
TITLES = {'Mr', 'Mrs', 'Ms', 'Miss', 'Dr', 'Rev', 'Prof'}


class Refused(Exception):
    """Something the shop can fix; the message says what."""

    def __init__(self, message, field=''):
        super().__init__(message)
        self.field = field


def open_to(invite=''):
    """May a shop apply now?"""
    if getattr(settings, 'PARTNER_SIGNUPS_OPEN', False):
        return True
    return bool(invite) and invite.strip().upper() in getattr(settings, 'PARTNER_INVITE_CODES', [])


def send_code(phone):
    """A code to a number the shop wants to confirm. Returns the number, normalised."""
    from apps.storefront.services import accounts
    try:
        return accounts.send_code(phone)
    except accounts.AccountRefused as exc:
        raise Refused(str(exc), 'phone')


def _confirmed(phone, code, field):
    from apps.storefront.services import accounts
    try:
        return accounts.check_code(phone, code)
    except accounts.AccountRefused as exc:
        raise Refused(str(exc), field)


def _need(data, key, label, limit=160):
    value = re.sub(r'\s+', ' ', str(data.get(key) or '')).strip()
    if not value:
        raise Refused(f'{label} is needed.', key)
    return value[:limit]


def _file(upload, kinds, label, field):
    if upload is None:
        raise Refused(f'{label} is needed.', field)
    if getattr(upload, 'content_type', '') not in kinds:
        raise Refused(f'{label} should be a photo (JPG or PNG).', field)
    if upload.size > MAX_IMAGE:
        raise Refused(f'{label} is too big. Under 8 MB, please.', field)
    return upload


def _short(upload, stem):
    """Stored names stay short: a FileField column holds 120 characters (lessons, 15 Nov)."""
    ext = (upload.name.rsplit('.', 1)[-1] if '.' in upload.name else 'jpg').lower()[:5]
    upload.name = f'{stem}.{ext}'
    return upload


def submit(data, shop_photo, logo):
    """
    Take an application. Returns the Partner, status APPLIED. Raises Refused
    with what to fix.
    """
    from apps.jobs.models import Service
    from apps.partners.models import Partner, PartnerRep
    from apps.storefront.services.accounts import find_lead, normalise_phone

    invite = str(data.get('invite') or '').strip()
    if not open_to(invite):
        raise Refused('Partner sign-ups open soon. If Farhat gave you an invite code, enter it.', 'invite')

    name = _need(data, 'name', 'Your business name', 120)
    kind = str(data.get('kind') or '')
    if kind not in Partner.Kind.values:
        raise Refused('Choose what kind of business you are.', 'kind')
    region = _need(data, 'region', 'Your region', 40)
    area = _need(data, 'area', 'Your town or area', 60)
    gps = _need(data, 'gps_address', 'Your Ghana Post GPS address', 20).upper()
    if not re.fullmatch(r'[A-Z]{2}-\d{3,4}-\d{3,4}', gps):
        raise Refused('That GPS address doesn\'t look right. It reads like GA-402-1187.', 'gps_address')
    landmark = _need(data, 'landmark', 'A landmark near you', 160)
    volume = str(data.get('monthly_volume') or '')
    if volume not in Partner.Volume.values:
        raise Refused('Tell us roughly how many jobs a month you\'d send.', 'monthly_volume')
    if str(data.get('accept_terms') or '').lower() not in ('1', 'true', 'yes', 'on'):
        raise Refused('Please read and accept the partner terms.', 'accept_terms')

    title = str(data.get('rep_title') or '').strip().rstrip('.').title()
    if title not in TITLES:
        raise Refused('Choose your title.', 'rep_title')
    first = _need(data, 'rep_first_name', 'Your first name', 60)
    last = _need(data, 'rep_last_name', 'Your last name', 60)
    role = str(data.get('rep_role') or '')
    if role not in PartnerRep.Role.values:
        raise Refused('Choose your role at the shop.', 'rep_role')

    ids = [i for i in re.findall(r'\d+', str(data.get('services') or ''))]
    services = list(Service.objects.filter(pk__in=ids, is_active=True, online=True))
    if not services:
        raise Refused('Choose at least one service you\'d send us.', 'services')

    _file(shop_photo, IMAGE_TYPES, 'A photo of your shop front', 'shop_photo')
    _file(logo, LOGO_TYPES, 'Your logo', 'logo')

    primary = normalise_phone(data.get('primary_phone'))
    rep_phone = normalise_phone(data.get('rep_phone'))
    if not primary:
        raise Refused('Enter the shop\'s main number.', 'primary_phone')
    if not rep_phone:
        raise Refused('Enter your own number.', 'rep_phone')
    secondary = normalise_phone(data.get('secondary_phone')) or ''

    # The same shop twice is one shop: by number, or by name in the same area.
    live = [Partner.Status.APPLIED, Partner.Status.ASKED, Partner.Status.APPROVED, Partner.Status.PAUSED]
    if Partner.objects.filter(status__in=live, primary_phone__in={primary, rep_phone}).exists() or \
            PartnerRep.objects.filter(partner__status__in=live, lead__phone=rep_phone).exists():
        raise Refused('This number is already on a partner account or application.', 'primary_phone')
    if Partner.objects.filter(status__in=live, name__iexact=name, area__iexact=area).exists():
        raise Refused(f'{name} in {area} has already applied. We\'ll be in touch on WhatsApp.', 'name')

    # Last, so a code isn't used up on an application that fails for another reason.
    _confirmed(primary, data.get('primary_code'), 'primary_code')
    if rep_phone != primary:
        _confirmed(rep_phone, data.get('rep_code'), 'rep_code')

    from apps.storefront.models import Lead
    with transaction.atomic():
        partner = Partner.objects.create(
            name=name, registered_name=str(data.get('registered_name') or '').strip()[:160], kind=kind,
            registration_number=str(data.get('registration_number') or '').strip()[:40],
            tin=str(data.get('tin') or '').strip()[:30],
            opening_hours=str(data.get('opening_hours') or '').strip()[:120],
            shop_photo=_short(shop_photo, 'shop'), logo=_short(logo, 'logo'),
            region=region, area=area, gps_address=gps, landmark=landmark,
            latitude=_coordinate(data.get('latitude'), 90), longitude=_coordinate(data.get('longitude'), 180),
            primary_phone=primary, secondary_phone=secondary,
            email=str(data.get('email') or '').strip()[:254],
            monthly_volume=volume, heard_from=str(data.get('heard_from') or '').strip()[:120],
            terms_version=TERMS_VERSION, terms_accepted_at=timezone.now(),
            messages_consent=str(data.get('messages_consent') or '').lower() in ('1', 'true', 'yes', 'on'),
            invite_code=invite.upper()[:40],
        )
        partner.services.set(services)
        lead = find_lead(rep_phone) or Lead.objects.create(phone=rep_phone, first_name=first)
        PartnerRep.objects.create(partner=partner, lead=lead, title=title, first_name=first,
                                  last_name=last, role=role)

    from apps.partners.services import review
    transaction.on_commit(lambda: review.put_to_owner(partner.pk))
    return partner


def _coordinate(value, limit):
    try:
        number = round(float(value), 6)
    except (TypeError, ValueError):
        return None
    return number if -limit <= number <= limit else None


def history(partner):
    """
    What Farhat already knows about these numbers as a customer: jobs, and
    anything owed. For the owner's card, so he decides with it in view.
    """
    from django.db.models import Q

    from apps.core.phones import lookup_forms
    from apps.customers.models import CustomerProfile
    from apps.finance.services.owing import OWING
    from apps.jobs.models import Job

    numbers = {partner.primary_phone} | {r.lead.phone for r in partner.reps.select_related('lead')}
    forms = set()
    for n in numbers:
        forms |= set(lookup_forms(n))
    people = CustomerProfile.objects.filter(Q(phone__in=forms) | Q(secondary_phone__in=forms))
    jobs = Job.objects.filter(customer__in=people)
    owed = [j for j in jobs.filter(OWING)]
    owing = sum((j.balance_due or 0) for j in owed)
    return {'jobs': jobs.count(), 'owing': owing}
