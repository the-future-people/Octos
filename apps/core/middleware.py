from django.http import JsonResponse
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from apps.accounts.models import CustomUser

SHADOW_BLOCKED_PREFIXES = (
    '/api/v1/jobs/',
    '/api/v1/finance/',
    '/api/v1/customers/',
    '/api/v1/inventory/',
    '/api/v1/communications/',
)

SAFE_METHODS = ('GET', 'HEAD', 'OPTIONS')


class ShadowUserMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            request.method not in SAFE_METHODS
            and any(request.path.startswith(p) for p in SHADOW_BLOCKED_PREFIXES)
        ):
            auth_header = request.headers.get('Authorization', '')
            if auth_header.startswith('Bearer '):
                token_str = auth_header.split(' ')[1]
                try:
                    token = AccessToken(token_str)
                    user_id = token['user_id']
                    user = CustomUser.objects.get(id=user_id)
                    if user.employment_status == 'SHADOW':
                        return JsonResponse(
                            {'detail': 'Your account has read-only shadow access until your start date.'},
                            status=403
                        )
                except (InvalidToken, TokenError, CustomUser.DoesNotExist):
                    pass

        return self.get_response(request)

# ── WebSocket JWT Authentication Middleware ────────────────────────────────────

from channels.middleware import BaseMiddleware
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser


@database_sync_to_async
def get_user_from_token(token_str):
    try:
        token = AccessToken(token_str)
        return CustomUser.objects.select_related('branch').get(id=token['user_id'])
    except (InvalidToken, TokenError, CustomUser.DoesNotExist):
        return AnonymousUser()


class JwtAuthMiddleware(BaseMiddleware):
    """
    Reads ?token=<access_token> from the WebSocket URL,
    validates it, and attaches the real user to scope['user'].
    Rejected connections get AnonymousUser which the consumer
    then closes with code 4001.
    """
    async def __call__(self, scope, receive, send):
        from urllib.parse import parse_qs
        qs     = parse_qs(scope.get('query_string', b'').decode())
        token  = qs.get('token', [None])[0]
        scope['user'] = await get_user_from_token(token) if token else AnonymousUser()
        return await super().__call__(scope, receive, send)