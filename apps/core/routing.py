# apps/core/routing.py
from django.urls import re_path
from apps.core.consumers import BranchConsumer

websocket_urlpatterns = [
    re_path(r'^ws/branch/$', BranchConsumer.as_asgi()),
]