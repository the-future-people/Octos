"""
The owner decides on every partner, on his WhatsApp line (23 Nov 2026).

The card shows the shop front, the details and what Farhat already knows
about these numbers as a customer, with three buttons:

  Approve       the account opens: a business customer, the partner ID,
                and a welcome on WhatsApp with 10% off the first job
  Ask for more  Octos asks him what to ask; his next message goes to the
                shop word for word
  Decline       a polite no

An application left unanswered for 14 days after "Ask for more" closes on
its own (close_stale); the shop can apply again any time.
"""
import io
import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

STALE_AFTER = timedelta(days=14)
QUESTION_WAIT = timedelta(hours=2)        # how long "what should I ask?" stays open


def say(phone, text, kind='partner'):
    """WhatsApp when the window is open, a text otherwise: how Octos reaches any customer."""
    from apps.communications.services.whatsapp_outbound import try_send_text
    from apps.storefront.services.sms import send_sms
    try:
        if try_send_text(phone, text, kind=kind):
            return True
    except Exception:
        logger.exception('Partner message by WhatsApp failed; texting instead')
    return send_sms(phone, text, kind=kind)


def _rep(partner):
    return partner.reps.filter(is_active=True).select_related('lead').order_by('pk').first()


def _photo_card(partner):
    """The shop front as a PNG small enough for a WhatsApp header, or None."""
    try:
        from PIL import Image, ImageOps
        partner.shop_photo.open('rb')
        with Image.open(partner.shop_photo) as image:
            image = ImageOps.exif_transpose(image).convert('RGB')
            image.thumbnail((1000, 1000))
            out = io.BytesIO()
            image.save(out, 'PNG', optimize=True)
            return out.getvalue()
    except Exception:
        logger.warning('Partner %s: shop photo could not be made into a card', partner.pk, exc_info=True)
        return None
    finally:
        try:
            partner.shop_photo.close()
        except Exception:
            pass


def card_text(partner):
    from apps.core.phones import display
    from apps.partners.services.apply import history
    rep = _rep(partner)
    known = history(partner)
    services = ', '.join(s.display_name or s.name for s in partner.services.all()[:6])
    lines = [
        'New partner application, boss 👀',
        '',
        f'*{partner.name}*, {partner.area} ({partner.gps_address})',
        f'Near {partner.landmark}',
    ]
    if rep:
        lines.append(f'{rep.title} {rep.first_name} {rep.last_name} ({rep.get_role_display().lower()}) · '
                     f'{display(rep.lead.phone)} ✓')
    if partner.primary_phone and (not rep or partner.primary_phone != rep.lead.phone):
        lines.append(f'Shop number {display(partner.primary_phone)} ✓')
    lines += ['', f'Would send: {services}', f'About {partner.get_monthly_volume_display().lower()}']
    if partner.registration_number:
        lines.append(f'Registered: {partner.registration_number}')
    lines.append('')
    if known['jobs']:
        owes = f", owes GHS {known['owing']:,.2f}" if known['owing'] else ', nothing owed'
        lines.append(f"Known to us: {known['jobs']} job{'s' if known['jobs'] != 1 else ''} as a customer{owes}.")
    else:
        lines.append('New to us: no jobs as a customer yet.')
    return '\n'.join(lines)


def put_to_owner(pk):
    """The application, on the owner's line, with the three buttons."""
    from apps.communications.models import OwnerMessage
    from apps.communications.services import owner_line
    from apps.partners.models import Partner
    partner = Partner.objects.filter(pk=pk, status=Partner.Status.APPLIED).first()
    if partner is None:
        return None
    return owner_line.tell(
        OwnerMessage.URGENT, card_text(partner), card=_photo_card(partner),
        buttons=[{'id': f'partner:approve:{pk}', 'title': 'Approve'},
                 {'id': f'partner:ask:{pk}', 'title': 'Ask for more'},
                 {'id': f'partner:decline:{pk}', 'title': 'Decline'}],
        key=f'partner-apply:{pk}', ref=f'partner:{pk}', knock=f'{partner.name} wants to be a partner')


def tap(reply_id):
    """One of the three buttons. Answers the owner either way."""
    from apps.communications.models import OwnerMessage
    from apps.communications.services.owner_line import tell
    from apps.partners.models import Partner
    _, action, pk = (reply_id.split(':') + ['', ''])[:3]
    partner = Partner.objects.filter(pk=pk if pk.isdigit() else 0).first()
    if partner is None:
        return tell(OwnerMessage.ANSWER, "I couldn't find that application any more.")
    if partner.status not in (Partner.Status.APPLIED, Partner.Status.ASKED):
        return tell(OwnerMessage.ANSWER, f'{partner.name} was already dealt with: '
                                         f'{partner.get_status_display().lower()}.')
    if action == 'approve':
        approve(partner)
        return tell(OwnerMessage.ANSWER, f'✅ {partner.name} is a partner: *{partner.shown_code}*. '
                                         f"I've welcomed them on WhatsApp with 10% off their first job.")
    if action == 'decline':
        decline(partner)
        return tell(OwnerMessage.ANSWER, f"Declined. I've told {partner.name} kindly.")
    if action == 'ask':
        Partner.objects.filter(awaiting_question=True).update(awaiting_question=False)
        Partner.objects.filter(pk=partner.pk).update(awaiting_question=True, asked_at=timezone.now())
        rep = _rep(partner)
        who = rep.first_name if rep else partner.name
        return tell(OwnerMessage.ANSWER, f'What should I ask {partner.name}? Type it, and I\'ll send it to '
                                         f'{who} word for word.')
    return tell(OwnerMessage.ANSWER, "I didn't understand that button.")


def waiting_for_question():
    """The application the owner was asked "what should I ask?" about, if still open."""
    from apps.partners.models import Partner
    return (Partner.objects.filter(awaiting_question=True, asked_at__gte=timezone.now() - QUESTION_WAIT,
                                   status__in=[Partner.Status.APPLIED, Partner.Status.ASKED])
            .order_by('-asked_at').first())


def take_question(partner, words):
    """His message is the question: it goes to the shop, and the clock starts."""
    from apps.communications.models import OwnerMessage
    from apps.communications.services.owner_line import tell
    from apps.partners.models import Partner
    rep = _rep(partner)
    Partner.objects.filter(pk=partner.pk).update(
        awaiting_question=False, asked_for=words.strip()[:2000], asked_at=timezone.now(),
        status=Partner.Status.ASKED)
    hello = f'Hi {rep.first_name}, ' if rep else 'Hi, '
    say(rep.lead.phone if rep else partner.primary_phone,
        f'{hello}thanks for applying to be a Farhat trade partner. Before we open your account, '
        f'we have one question:\n\n{words.strip()}\n\nJust reply here.')
    return tell(OwnerMessage.ANSWER, f'Sent to {partner.name} ✅ If they don\'t answer in 14 days, '
                                     f'the application closes on its own.')


def _business_customer(partner):
    """
    The business its jobs and receipts belong to. The shop's own number when
    it's free; an existing business record on it is reused. When the number
    is already a person's (usually the owner's own), the business gets the
    secondary number, or a placeholder made from its ID: messages to a
    partner go to its contacts, never to this field.
    """
    from apps.customers.models import CustomerProfile, Membership
    existing = CustomerProfile.objects.filter(phone=partner.primary_phone).first()
    if existing and existing.customer_type in ('BUSINESS', 'INSTITUTION'):
        business = existing
    else:
        phone = partner.primary_phone
        if existing or not phone:
            free = partner.secondary_phone and not CustomerProfile.objects.filter(phone=partner.secondary_phone).exists()
            phone = partner.secondary_phone if free else f'TP-{partner.code}'
        business = CustomerProfile.objects.create(
            phone=phone, company_name=partner.name, first_name=partner.name[:100],
            customer_type='BUSINESS', email=partner.email,
            address=f'{partner.area}, near {partner.landmark} ({partner.gps_address})',
        )
    # The rep, if Farhat already knows them as a person, is linked to the business.
    rep = _rep(partner)
    if rep:
        person = rep.lead.customer if rep.lead.customer_id else \
            CustomerProfile.objects.filter(phone=rep.lead.phone).exclude(pk=business.pk).first()
        if person and not Membership.objects.filter(person=person, organisation=business).exists():
            role = {'OWNER': Membership.Role.OWNER, 'MANAGER': Membership.Role.REP}.get(rep.role, Membership.Role.STAFF)
            Membership.objects.create(person=person, organisation=business, role=role, named=True,
                                      note='Trade partner rep')
    return business


def approve(partner):
    from apps.partners.models import Partner
    from apps.partners.services.ids import new_code
    from apps.storefront.services.messages import STOREFRONT
    with transaction.atomic():
        partner = Partner.objects.select_for_update().get(pk=partner.pk)
        if partner.status not in (Partner.Status.APPLIED, Partner.Status.ASKED):
            return partner
        partner.code = partner.code or new_code(partner.area)
        partner.customer = partner.customer or _business_customer(partner)
        partner.status = Partner.Status.APPROVED
        partner.decided_at = timezone.now()
        partner.awaiting_question = False
        partner.save()
    rep = _rep(partner)
    hello = f'Hi {rep.first_name}' if rep else 'Hello'
    text = (f'{hello}, welcome to Farhat Trade Partners 🎉\n\n'
            f'{partner.name} is now a partner. Your partner ID is *{partner.shown_code}*: it goes on every '
            f'parcel we pack for you.\n\n'
            f'Your first job is 10% off, and every job after that is 6% under the walk-in price.\n\n'
            f'Sign in with this number at {STOREFRONT}/partners to send your first job.')
    transaction.on_commit(lambda: say(rep.lead.phone if rep else partner.primary_phone, text))
    return partner


def decline(partner):
    from apps.partners.models import Partner
    Partner.objects.filter(pk=partner.pk).update(status=Partner.Status.DECLINED, decided_at=timezone.now(),
                                                 awaiting_question=False)
    rep = _rep(partner)
    hello = f'Hi {rep.first_name}' if rep else 'Hello'
    say(rep.lead.phone if rep else partner.primary_phone,
        f'{hello}, thank you for applying to be a Farhat trade partner. We can\'t open a partner account '
        f'for {partner.name} right now. You\'re always welcome to order from us as a customer, and to '
        f'apply again later.')


def close_stale(now=None):
    """'Ask for more' with no answer in 14 days: closed. Returns how many."""
    from apps.partners.models import Partner
    now = now or timezone.now()
    return Partner.objects.filter(status=Partner.Status.ASKED, asked_at__lt=now - STALE_AFTER).update(
        status=Partner.Status.CLOSED, decided_at=now, awaiting_question=False)
