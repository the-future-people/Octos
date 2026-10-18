"""
How the app proves who it is: `Authorization: App <token>` on a request.

The storefront is otherwise unauthenticated; this only identifies an app
customer where a view asks for one. It never makes anyone staff.
"""

from django.contrib.auth.models import AnonymousUser
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed


class AppSessionAuthentication(BaseAuthentication):
    keyword = 'App'

    def authenticate(self, request):
        from apps.storefront.services.accounts import session_for

        header = request.META.get('HTTP_AUTHORIZATION', '')
        if not header.startswith(self.keyword + ' '):
            return None
        session = session_for(header[len(self.keyword) + 1:].strip())
        if session is None:
            raise AuthenticationFailed('Your session has ended. Sign in again.')
        return AnonymousUser(), session

    def authenticate_header(self, request):
        return self.keyword