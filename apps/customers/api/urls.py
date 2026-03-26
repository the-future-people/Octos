from django.urls import path
from . import views

urlpatterns = [
    # ── Customer ──────────────────────────────────────────────
    path('', views.CustomerListView.as_view(), name='customer-list'),
    path('create/', views.CustomerCreateView.as_view(), name='customer-create'),
    path('lookup/', views.CustomerLookupView.as_view(), name='customer-lookup'),
    path('<int:pk>/', views.CustomerDetailView.as_view(), name='customer-detail'),

    # ── Credit accounts ───────────────────────────────────────
    path('credit/', views.CreditAccountListView.as_view(), name='credit-list'),
    path('credit/nominate/', views.CreditAccountNominateView.as_view(), name='credit-nominate'),
    path('credit/<int:pk>/', views.CreditAccountDetailView.as_view(), name='credit-detail'),
    path('credit/<int:pk>/approve/', views.CreditAccountApproveView.as_view(), name='credit-approve'),
    path('credit/<int:pk>/suspend/', views.CreditAccountSuspendView.as_view(), name='credit-suspend'),
    path('credit/<int:pk>/settle/', views.CreditSettleView.as_view(), name='credit-settle'),
    path('credit/<int:pk>/payments/', views.CreditPaymentHistoryView.as_view(), name='credit-payments'),
]