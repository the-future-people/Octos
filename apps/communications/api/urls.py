from django.urls import path
from . import views

urlpatterns = [
    # Conversations
    path('', views.ConversationListView.as_view(), name='conversation-list'),
    path('<int:pk>/', views.ConversationDetailView.as_view(), name='conversation-detail'),
    path('<int:pk>/reply/', views.ConversationReplyView.as_view(), name='conversation-reply'),
    path('<int:pk>/assign/', views.ConversationAssignView.as_view(), name='conversation-assign'),
    path('<int:pk>/resolve/', views.ConversationResolveView.as_view(), name='conversation-resolve'),
    path('<int:pk>/link-job/', views.ConversationLinkJobView.as_view(), name='conversation-link-job'),

    # Webhooks
    path('webhook/inbound/', views.InboundWebhookView.as_view(), name='webhook-inbound'),
]