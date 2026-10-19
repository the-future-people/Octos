"""
Sign up and sign in for the Print Octos app.

POST account/code/      { phone }                          text a code
POST account/verify/    { phone, code, first_name?, device? }  sign in or up
GET  account/me/        (App token)                        who is signed in
POST account/signout/   (App token)                        end this session
"""

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.storefront.auth import AppSessionAuthentication
from apps.storefront.services.accounts import (
    AccountRefused, mask, send_code, sign_out, verify_code,
)


def _account(lead):
    return {
        'first_name': lead.first_name,
        'phone': mask(lead.phone),
        # The customer's own number, for their own orders: shown masked,
        # sent in full to the signed-in app that owns it.
        'number': lead.phone,
        'order_count': lead.order_count,
    }


class _Public(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    # The same limit as guessing a customer code: a few a minute per device.
    throttle_scope = 'storefront_code'


class AccountCodeView(_Public):
    def post(self, request):
        try:
            phone = send_code(request.data.get('phone'))
        except AccountRefused as refused:
            return Response({'detail': str(refused)}, status=status.HTTP_400_BAD_REQUEST)
        from apps.storefront.services.accounts import find_lead
        return Response({
            'sent_to': mask(phone),
            # So the app knows whether to ask for a first name.
            'new_customer': find_lead(phone) is None,
        })


class AccountVerifyView(_Public):
    def post(self, request):
        try:
            lead, token = verify_code(
                request.data.get('phone'), request.data.get('code'),
                first_name=request.data.get('first_name', ''),
                device=request.data.get('device', ''),
            )
        except AccountRefused as refused:
            return Response({'detail': str(refused)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'token': token, 'account': _account(lead)}, status=status.HTTP_201_CREATED)


class _SignedIn(APIView):
    authentication_classes = [AppSessionAuthentication]
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'storefront'

    def session(self, request):
        from apps.storefront.models import AppSession
        return request.auth if isinstance(request.auth, AppSession) else None

    def refused(self):
        return Response({'detail': 'Sign in to continue.'}, status=status.HTTP_401_UNAUTHORIZED)


class AccountMeView(_SignedIn):
    def get(self, request):
        session = self.session(request)
        if session is None:
            return self.refused()
        return Response(_account(session.lead))


class AccountSignOutView(_SignedIn):
    def post(self, request):
        session = self.session(request)
        if session is None:
            return self.refused()
        sign_out(session)
        return Response({'signed_out': True})

class AccountOrdersView(_SignedIn):
    """GET account/orders/: the signed-in customer's orders, active and collected."""

    def get(self, request):
        from apps.storefront.services.accounts import orders_for
        session = self.session(request)
        if session is None:
            return self.refused()
        return Response(orders_for(session.lead))

# ── My orders ────────────────────────────────────────────────────

def leads_for(lead):
    """
    Every Lead on this number, however the website wrote it down: an
    order placed as "024 499 9888" and one as "0244999888" are the same
    customer's.
    """
    from apps.storefront.models import Lead

    phone = normalise_phone(lead.phone) or lead.phone
    same = [
        other for other in Lead.objects.filter(phone__contains=phone[-4:])
        if normalise_phone(other.phone) == phone
    ]
    return same or [lead]


# The customer's words for where an order has got to.
_STAGE = {
    'RECEIVED': 'inspecting',
    'IN_PRODUCTION': 'press',
    'FINISHING': 'finishing',
    'QUALITY_CHECK': 'finishing',
    'DONE': 'ready',
}


def _stage(order):
    job = order.job
    if job is None:
        return 'paid'
    if job.handover_state == 'HANDED_OVER':
        return 'collected'
    return _STAGE.get(job.work_state, 'paid')


def orders_for(lead):
    """
    The customer's paid orders, newest first: active ones with their stage
    and time left, collected ones with when. Cancelled work is left out;
    carts never paid for are not orders.
    """
    from apps.jobs.models import JobStatusLog
    from apps.jobs.services.estimates import estimate
    from apps.storefront.models import OnlineOrder

    orders = (
        OnlineOrder.objects
        .filter(lead__in=leads_for(lead), paid_at__isnull=False)
        .select_related('job', 'branch')
        .order_by('-paid_at')
    )

    active, collected = [], []
    for order in orders:
        job = order.job
        if job is not None and job.status in ('CANCELLED', 'VOIDED'):
            continue

        lines = order.line_items or []
        first = lines[0].get('service_name', 'Order') if lines else 'Order'
        item = {
            'order_number': order.order_number,
            # Their own order: the link that opens its tracking page.
            'token': order.access_token,
            'summary': first if len(lines) <= 1 else f'{first} and {len(lines) - 1} more',
            'total': f'{order.total:.2f}',
            'paid_at': order.paid_at.isoformat(),
            'branch': order.branch.name if order.branch_id else None,
            'promised_for': order.promised_for.isoformat() if order.promised_for else None,
            'stage': _stage(order),
        }

        if item['stage'] == 'collected':
            at = (
                JobStatusLog.objects
                .filter(job=job, to_status='HANDED_OVER')
                .order_by('transitioned_at')
                .values_list('transitioned_at', flat=True)
                .first()
            )
            item['collected_at'] = (at or job.updated_at).isoformat()
            collected.append(item)
        else:
            try:
                found = estimate(job) if job is not None else None
            except Exception:
                found = None
            item['estimate'] = found.as_dict() if found else None
            active.append(item)

    return {'active': active, 'collected': collected}

class AccountDeviceView(_SignedIn):
    """POST account/device/ { token, platform }: where to push for this phone."""

    def post(self, request):
        from django.utils import timezone
        from apps.storefront.models import DeviceToken
        session = self.session(request)
        if session is None:
            return self.refused()
        token = (request.data.get('token') or '').strip()
        if not token:
            return Response({'detail': 'No device token.'}, status=status.HTTP_400_BAD_REQUEST)
        DeviceToken.objects.update_or_create(
            token=token[:255],
            defaults={
                'session': session,
                'platform': (request.data.get('platform') or '')[:10],
                'last_seen_at': timezone.now(),
            },
        )
        return Response({'registered': True})


class AccountNotificationsView(_SignedIn):
    """GET account/notifications/: the inbox, newest first, with the unread count."""

    def get(self, request):
        from apps.storefront.models import AppNotification
        from apps.storefront.services.accounts import leads_for
        session = self.session(request)
        if session is None:
            return self.refused()
        notes = (
            AppNotification.objects
            .filter(lead__in=leads_for(session.lead))
            .select_related('order')[:50]
        )
        return Response({
            'unread': sum(1 for n in notes if n.read_at is None),
            'items': [{
                'id': n.id,
                'kind': n.kind,
                'title': n.title,
                'body': n.body,
                'at': n.created_at.isoformat(),
                'read': n.read_at is not None,
                'order_number': n.order.order_number if n.order_id else None,
                'token': n.order.access_token if n.order_id else None,
            } for n in notes],
        })


class AccountNotificationsReadView(_SignedIn):
    """POST account/notifications/read/: everything in the inbox marked read."""

    def post(self, request):
        from django.utils import timezone
        from apps.storefront.models import AppNotification
        from apps.storefront.services.accounts import leads_for
        session = self.session(request)
        if session is None:
            return self.refused()
        AppNotification.objects.filter(
            lead__in=leads_for(session.lead), read_at__isnull=True,
        ).update(read_at=timezone.now())
        return Response({'read': True})