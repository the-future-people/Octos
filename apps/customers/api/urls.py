from django.urls import path
from . import views

urlpatterns = [
    path('', views.CustomerListView.as_view(), name='customer-list'),
    path('create/', views.CustomerCreateView.as_view(), name='customer-create'),
    path('lookup/', views.CustomerLookupView.as_view(), name='customer-lookup'),
    path('<int:pk>/', views.CustomerDetailView.as_view(), name='customer-detail'),
]