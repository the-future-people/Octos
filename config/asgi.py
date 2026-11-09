# config/asgi.py
import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from urllib.parse import urlparse
from channels.security.websocket import OriginValidator

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# Initialise Django ASGI application early to ensure AppRegistry is ready
django_asgi_app = get_asgi_application()

from apps.core.routing import websocket_urlpatterns
from apps.core.middleware import JwtAuthMiddleware
from django.conf import settings


def _live_origins():
    """
    Websites allowed to open a live connection (9 Nov 2026): the ones the
    server already trusts for the portal (CORS_ALLOWED_ORIGINS, such as
    octos-web.vercel.app) and its own addresses. AllowedHostsOriginValidator
    allowed only the latter, so the portal was refused every time.
    """
    hosts = {h.strip() for h in settings.ALLOWED_HOSTS if h.strip() and h.strip() != '*'}
    for origin in getattr(settings, 'CORS_ALLOWED_ORIGINS', []):
        host = urlparse(origin).hostname
        if host:
            hosts.add(host)
    return sorted(hosts)

application = ProtocolTypeRouter({
    # Standard HTTP — handed straight to Django as before
    'http': django_asgi_app,

    # WebSocket — validated by origin, then authenticated by JWT
    'websocket': OriginValidator(
        JwtAuthMiddleware(
            URLRouter(websocket_urlpatterns)
        ),
        _live_origins(),
    ),
})