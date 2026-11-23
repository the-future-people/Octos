"""
The trade-partner API for Print Octos (23 Nov 2026).

    GET  /api/v1/partners/open/?invite=   may a shop apply now, and the services it can choose
    POST /api/v1/partners/code/           a code to a number the shop is confirming
    POST /api/v1/partners/apply/          the application (multipart: photo and logo)
    GET  /api/v1/partners/me/             the signed-in rep's partner (App session)

Signing in is the app's own: account/code/ and account/verify/ with the rep's
number. A rep's session is an ordinary Print Octos session; what makes it a
partner's is the PartnerRep row.
"""
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.partners.services import apply as applying
from apps.partners.services import portal


def _partner_services():
    from apps.jobs.models import Service
    from apps.jobs.services.availability import can_make
    found = Service.objects.filter(is_active=True, online=True).order_by('category', 'name')
    seen, out = set(), []
    for s in found:
        name = s.display_name or s.name
        if name in seen or not can_make(s):
            continue
        seen.add(name)
        out.append({'id': s.id, 'name': name, 'category': s.category})
    return out


class _Public(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []


class OpenView(_Public):
    def get(self, request):
        from apps.partners.models import Partner, PartnerRep
        invite = request.query_params.get('invite', '')
        return Response({
            'open': applying.open_to(invite),
            'terms_version': applying.TERMS_VERSION,
            'kinds': [{'id': k, 'name': n} for k, n in Partner.Kind.choices],
            'volumes': [{'id': k, 'name': n} for k, n in Partner.Volume.choices],
            'titles': sorted(applying.TITLES),
            'roles': [{'id': k, 'name': n} for k, n in PartnerRep.Role.choices],
            'services': _partner_services(),
        })


class CodeView(_Public):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'storefront_code'

    def post(self, request):
        if not applying.open_to(request.data.get('invite', '')):
            return Response({'detail': 'Partner sign-ups open soon.', 'field': 'invite'},
                            status=status.HTTP_403_FORBIDDEN)
        try:
            phone = applying.send_code(request.data.get('phone'))
        except applying.Refused as refused:
            return Response({'detail': str(refused), 'field': refused.field}, status=status.HTTP_400_BAD_REQUEST)
        from apps.storefront.services.accounts import mask
        return Response({'sent_to': mask(phone)})


class ApplyView(_Public):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'storefront'

    def post(self, request):
        from apps.partners.services import access
        try:
            partner = applying.submit(request.data, request.FILES.get('shop_photo'), request.FILES.get('logo'))
        except applying.Refused as refused:
            return Response({'detail': str(refused), 'field': refused.field}, status=status.HTTP_400_BAD_REQUEST)
        # The phone is confirmed and the password set: the account exists, so
        # they're logged in straight away, to wait for the owner's decision.
        rep = partner.reps.select_related('lead').first()
        return Response({'status': partner.status, 'name': partner.name, 'token': access.session(rep.lead)},
                        status=status.HTTP_201_CREATED)


class LoginView(_Public):
    """POST {phone, password} -> {token}. Five wrong tries lock the number for 15 minutes."""
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'storefront_code'

    def post(self, request):
        from apps.partners.services import access
        try:
            _, token = access.login(request.data.get('phone'), request.data.get('password'))
        except access.Refused as refused:
            return Response({'detail': str(refused), 'field': refused.field}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'token': token})


class PasswordCodeView(_Public):
    """POST {phone}: a code to set a new password. The answer is the same whether or not the number is a rep's."""
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'storefront_code'

    def post(self, request):
        from apps.partners.services import access
        try:
            shown = access.send_reset_code(request.data.get('phone'))
        except access.Refused as refused:
            return Response({'detail': str(refused), 'field': refused.field}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'sent_to': shown})


class PasswordResetView(_Public):
    """POST {phone, code, password} -> {token}: the new password is set and they're logged in."""
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'storefront_code'

    def post(self, request):
        from apps.partners.services import access
        try:
            _, token = access.reset(request.data.get('phone'), request.data.get('code'), request.data.get('password'))
        except access.Refused as refused:
            return Response({'detail': str(refused), 'field': refused.field}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'token': token})



def _url(field):
    try:
        return field.url if field else ''
    except Exception:
        return ''


def partner_for(session):
    """The partner a signed-in rep acts for, or None."""
    from apps.partners.models import PartnerRep
    rep = (PartnerRep.objects.select_related('partner').filter(lead_id=session.lead_id, is_active=True)
           .order_by('-partner__applied_at').first())
    return (rep.partner, rep) if rep else (None, None)


class MeView(APIView):
    permission_classes = [AllowAny]

    def get_authenticators(self):
        from apps.storefront.auth import AppSessionAuthentication
        return [AppSessionAuthentication()]

    def get(self, request):
        session = request.auth
        if session is None:
            return Response({'detail': 'Sign in first.'}, status=status.HTTP_401_UNAUTHORIZED)
        partner, rep = partner_for(session)
        if partner is None:
            return Response({'detail': 'This number isn\'t on a partner account.'}, status=status.HTTP_404_NOT_FOUND)
        return Response({
            'code': partner.shown_code,
            'status': partner.status,
            'status_label': partner.get_status_display(),
            'name': partner.name,
            'area': partner.area,
            'landmark': partner.landmark,
            'since': partner.decided_at.isoformat() if partner.decided_at and partner.active else None,
            'applied_at': partner.applied_at.isoformat(),
            'asked_for': partner.asked_for if partner.status == partner.Status.ASKED else '',
            'shop_photo': _url(partner.shop_photo),
            'logo': _url(partner.logo),
            'rep': {'title': rep.title, 'first_name': rep.first_name, 'last_name': rep.last_name,
                    'role': rep.role},
            # Only an approved (or paused) partner has jobs to show.
            **(portal.dashboard(partner) if partner.status in (partner.Status.APPROVED, partner.Status.PAUSED) else {}),
        })


class OrderView(APIView):
    """
    POST /api/v1/partners/orders/  {reference}

    Starts a partner's order. From here the page uses the storefront's own
    steps with the order's token (lines, files, branch, pay), and every save
    prices it at the trade price (OnlineOrder.save, partners/services/pricing).
    """
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'storefront'

    def get_authenticators(self):
        from apps.storefront.auth import AppSessionAuthentication
        return [AppSessionAuthentication()]

    def post(self, request):
        from apps.storefront.models import OnlineOrder
        session = request.auth
        if session is None:
            return Response({'detail': 'Sign in first.'}, status=status.HTTP_401_UNAUTHORIZED)
        partner, rep = partner_for(session)
        if partner is None or partner.status != partner.Status.APPROVED:
            return Response({'detail': 'Only an approved partner can send jobs.'}, status=status.HTTP_403_FORBIDDEN)
        reference = ' '.join(str(request.data.get('reference') or '').split())[:80]
        order = OnlineOrder.objects.create(lead=rep.lead, partner=partner, partner_reference=reference)
        return Response({'order_number': order.order_number, 'access_token': order.access_token,
                         'reference': reference}, status=status.HTTP_201_CREATED)


class SignOutView(MeView):
    def post(self, request):
        from apps.storefront.services.accounts import sign_out
        if request.auth is not None:
            sign_out(request.auth)
        return Response({'ok': True})
