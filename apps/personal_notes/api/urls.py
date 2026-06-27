from django.urls import path
from .views import (
    PersonalNoteListCreateView,
    PersonalNoteDetailView,
    PinStatusView,
    SetPinView,
    VerifyPinView,
    DueRemindersView,
    DismissReminderView,
)

urlpatterns = [
    path('',                          PersonalNoteListCreateView.as_view(), name='note-list-create'),
    path('<int:pk>/',                 PersonalNoteDetailView.as_view(),      name='note-detail'),
    path('pin/status/',               PinStatusView.as_view(),               name='note-pin-status'),
    path('pin/set/',                  SetPinView.as_view(),                  name='note-pin-set'),
    path('pin/verify/',               VerifyPinView.as_view(),               name='note-pin-verify'),
    path('due-reminders/',            DueRemindersView.as_view(),            name='note-due-reminders'),
    path('<int:pk>/dismiss-reminder/', DismissReminderView.as_view(),         name='note-dismiss-reminder'),
]