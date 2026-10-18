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