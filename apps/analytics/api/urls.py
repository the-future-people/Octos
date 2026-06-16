from django.urls import path
from .views import (
    SessionStartView,
    SessionHeartbeatView,
    SessionEventView,
    SessionEndView,
    EODPredictionView,
)

urlpatterns = [
    path('session/start/',     SessionStartView.as_view(),     name='session-start'),
    path('session/heartbeat/', SessionHeartbeatView.as_view(), name='session-heartbeat'),
    path('session/event/',     SessionEventView.as_view(),     name='session-event'),
    path('session/end/',       SessionEndView.as_view(),       name='session-end'),
    path('prediction/',        EODPredictionView.as_view(),    name='eod-prediction'),
]