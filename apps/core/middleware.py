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