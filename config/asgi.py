# config/asgi.py
import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# Initialise Django ASGI application early to ensure AppRegistry is ready
django_asgi_app = get_asgi_application()

from apps.core.routing import websocket_urlpatterns
from apps.core.middleware import JwtAuthMiddleware

application = ProtocolTypeRouter({
    # Standard HTTP — handed straight to Django as before
    'http': django_asgi_app,

    # WebSocket — validated by origin, then authenticated by JWT
    'websocket': AllowedHostsOriginValidator(
        JwtAuthMiddleware(
            URLRouter(websocket_urlpatterns)
        )
    ),
})