from django.urls import path
from . import views
from .whatsapp_webhook import WhatsAppWebhookView

urlpatterns = [
    # Conversations
    path('', views.ConversationListView.as_view(), name='conversation-list'),
    path('<int:pk>/', views.ConversationDetailView.as_view(), name='conversation-detail'),
    path('<int:pk>/reply/', views.ConversationReplyView.as_view(), name='conversation-reply'),
    path('<int:pk>/assign/', views.ConversationAssignView.as_view(), name='conversation-assign'),
    path('<int:pk>/resolve/', views.ConversationResolveView.as_view(), name='conversation-resolve'),
    path('<int:pk>/link-job/', views.ConversationLinkJobView.as_view(), name='conversation-link-job'),
    path('<int:pk>/take-over/', views.ConversationTakeOverView.as_view(), name='conversation-take-over'),
    path('<int:pk>/hand-back/', views.ConversationHandBackView.as_view(), name='conversation-hand-back'),
    path('<int:pk>/at-counter/', views.ConversationAtCounterView.as_view(), name='conversation-at-counter'),

    # Webhooks
    path('webhook/whatsapp/', WhatsAppWebhookView.as_view(), name='webhook-whatsapp'),
]