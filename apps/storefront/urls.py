from django.urls import path

from . import views

# Order matters. `orders/<str:order_number>/` matches anything that
# starts with an order number, so every more specific route has to come
# before it or it never runs.
urlpatterns = [
    path('catalogue/', views.CatalogueView.as_view(), name='storefront-catalogue'),
    path('orders/', views.OrderCreateView.as_view(), name='storefront-order-create'),
    path('webhook/paystack/', views.PaystackWebhookView.as_view(), name='storefront-paystack-webhook'),

    path('orders/<str:order_number>/identify/', views.OrderIdentifyView.as_view(), name='storefront-order-identify'),
    path('orders/<str:order_number>/code/', views.OrderCodeView.as_view(), name='storefront-order-code'),
    path('orders/<str:order_number>/pay/', views.OrderPayView.as_view(), name='storefront-order-pay'),
    path('orders/<str:order_number>/file/', views.OrderFileView.as_view(), name='storefront-order-file'),
    path('orders/<str:order_number>/branches/', views.OrderBranchesView.as_view(), name='storefront-order-branches'),

    path('orders/<str:order_number>/', views.OrderDetailView.as_view(), name='storefront-order-detail'),
    path('check/', views.ArtworkCheckView.as_view(), name='storefront-artwork-check'),
    path('commit/', views.CommitView.as_view(), name='storefront-commit'),
]