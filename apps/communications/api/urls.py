from django.urls import path
from . import views
from .whatsapp_webhook import WhatsAppWebhookView

urlpatterns = [
    # Conversations
    path('', views.ConversationListView.as_view(), name='conversation-list'),
    path('messages/<int:pk>/file/', views.MessageFileView.as_view(), name='message-file'),
    path('start/', views.ConversationStartView.as_view(), name='conversation-start'),
    path('<int:pk>/', views.ConversationDetailView.as_view(), name='conversation-detail'),
    path('<int:pk>/reply/', views.ConversationReplyView.as_view(), name='conversation-reply'),
    path('<int:pk>/assign/', views.ConversationAssignView.as_view(), name='conversation-assign'),
    path('<int:pk>/resolve/', views.ConversationResolveView.as_view(), name='conversation-resolve'),
    path('<int:pk>/link-job/', views.ConversationLinkJobView.as_view(), name='conversation-link-job'),
    path('<int:pk>/take-over/', views.ConversationTakeOverView.as_view(), name='conversation-take-over'),
    path('<int:pk>/hand-back/', views.ConversationHandBackView.as_view(), name='conversation-hand-back'),
    path('<int:pk>/at-counter/', views.ConversationAtCounterView.as_view(), name='conversation-at-counter'),
    path('<int:pk>/link-customer/', views.ConversationLinkCustomerView.as_view(), name='conversation-link-customer'),
    path('<int:pk>/photos-pdf/', views.ConversationPhotosPdfView.as_view(), name='conversation-photos-pdf'),

    # Webhooks
    path('webhook/whatsapp/', WhatsAppWebhookView.as_view(), name='webhook-whatsapp'),
]