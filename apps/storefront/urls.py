from django.urls import path

from . import views
from apps.storefront import account_views
from apps.storefront import route_views
# Order matters. `orders/<str:order_number>/` matches anything that
# starts with an order number, so every more specific route has to come
# before it or it never runs.


urlpatterns = [
    path('catalogue/', views.CatalogueView.as_view(), name='storefront-catalogue'),
    path('account/code/', account_views.AccountCodeView.as_view(), name='storefront-account-code'),
    path('account/verify/', account_views.AccountVerifyView.as_view(), name='storefront-account-verify'),
    path('account/me/', account_views.AccountMeView.as_view(), name='storefront-account-me'),
    path('account/signout/', account_views.AccountSignOutView.as_view(), name='storefront-account-signout'),
    path('account/orders/',  account_views.AccountOrdersView.as_view(),  name='account-orders'),
    path('account/device/',              account_views.AccountDeviceView.as_view(),            name='account-device'),
    path('account/notifications/',       account_views.AccountNotificationsView.as_view(),     name='account-notifications'),
    path('account/notifications/read/',  account_views.AccountNotificationsReadView.as_view(), name='account-notifications-read'),
    path('orders/', views.OrderCreateView.as_view(), name='storefront-order-create'),
    path('webhook/paystack/', views.PaystackWebhookView.as_view(), name='storefront-paystack-webhook'),

    path('orders/<str:order_number>/identify/', views.OrderIdentifyView.as_view(), name='storefront-order-identify'),
    path('orders/<str:order_number>/code/', views.OrderCodeView.as_view(), name='storefront-order-code'),
    path('orders/<str:order_number>/pay/', views.OrderPayView.as_view(), name='storefront-order-pay'),
    path('orders/<str:order_number>/file/', views.OrderFileView.as_view(), name='storefront-order-file'),
    path('orders/<str:order_number>/branches/', views.OrderBranchesView.as_view(), name='storefront-order-branches'),

    path('orders/<str:order_number>/', views.OrderDetailView.as_view(), name='storefront-order-detail'),
    path('check/', views.ArtworkCheckView.as_view(), name='storefront-artwork-check'),
    path('quote/', views.QuoteView.as_view(), name='storefront-quote'),
    path('commit/', views.CommitView.as_view(), name='storefront-commit'),
    path('find/', views.FindOrderView.as_view(), name='storefront-find-order'),
    path('t/<str:code>/', views.ShortLinkView.as_view(), name='storefront-short-link'),
    path('confirm/<str:reference>/', views.PaymentConfirmationView.as_view(), name='storefront-confirm-payment'),
    path('route/', route_views.RouteView.as_view(), name='route'),
]