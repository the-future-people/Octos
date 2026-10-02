from django.urls import path
from apps.storefront.models import Lead, OnlineOrder, OrderFile, PaystackEvent
from . import views

urlpatterns = [
    path('catalogue/', views.CatalogueView.as_view(), name='storefront-catalogue'),
    path('webhook/paystack/', views.PaystackWebhookView.as_view(), name='storefront-paystack-webhook'),
    path('orders/<str:order_number>/file/', views.OrderFileView.as_view(), name='storefront-order-file'),
    path('orders/', views.OrderCreateView.as_view(), name='storefront-order-create'),
    path('orders/<str:order_number>/', views.OrderDetailView.as_view(), name='storefront-order-detail'),
    path('orders/<str:order_number>/identify/', views.OrderIdentifyView.as_view(), name='storefront-order-identify'),
    path('orders/<str:order_number>/code/', views.OrderCodeView.as_view(), name='storefront-order-code'),
    path('orders/<str:order_number>/pay/', views.OrderPayView.as_view(), name='storefront-order-pay'),
]