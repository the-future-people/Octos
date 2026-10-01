from django.urls import path

from . import views

urlpatterns = [
    path('catalogue/', views.CatalogueView.as_view(), name='storefront-catalogue'),
    path('orders/', views.OrderCreateView.as_view(), name='storefront-order-create'),
    path('orders/<str:order_number>/', views.OrderDetailView.as_view(), name='storefront-order-detail'),
    path('orders/<str:order_number>/identify/', views.OrderIdentifyView.as_view(), name='storefront-order-identify'),
    path('orders/<str:order_number>/code/', views.OrderCodeView.as_view(), name='storefront-order-code'),
]