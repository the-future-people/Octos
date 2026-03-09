from django.urls import path
from . import views

urlpatterns = [
    # Jobs
    path('', views.JobListView.as_view(), name='job-list'),
    path('create/', views.JobCreateView.as_view(), name='job-create'),
    path('<int:pk>/', views.JobDetailView.as_view(), name='job-detail'),
    path('<int:pk>/transition/', views.JobTransitionView.as_view(), name='job-transition'),
    path('<int:pk>/route/suggest/', views.JobRouteSuggestView.as_view(), name='job-route-suggest'),
    path('<int:pk>/route/confirm/', views.JobRouteConfirmView.as_view(), name='job-route-confirm'),

    # Services
    path('services/', views.ServiceListView.as_view(), name='service-list'),

    # Pricing
    path('pricing/', views.PricingRuleListView.as_view(), name='pricing-list'),
    path('price/calculate/', views.PriceCalculateView.as_view(), name='price-calculate'),
]