from django.urls import path
from . import views

urlpatterns = [
    # Jobs CRUD
    path('',        views.JobListView.as_view(),   name='job-list'),
    path('create/', views.JobCreateView.as_view(), name='job-create'),
    path('<int:pk>/', views.JobDetailView.as_view(), name='job-detail'),

    # Job actions
    path('<int:pk>/transition/', views.JobTransitionView.as_view(),  name='job-transition'),
    path('<int:pk>/files/',      views.JobFileUploadView.as_view(),  name='job-file-upload'),

    # Routing
    path('<int:pk>/route/suggest/', views.JobRouteSuggestView.as_view(),  name='job-route-suggest'),
    path('<int:pk>/route/confirm/', views.JobRouteConfirmView.as_view(),  name='job-route-confirm'),

    # Cashier
    path('cashier/queue/',           views.CashierQueueView.as_view(),          name='cashier-queue'),
    path('cashier/summary/',         views.CashierSummaryView.as_view(),         name='cashier-summary'),
    path('<int:pk>/cashier/confirm/', views.CashierConfirmPaymentView.as_view(), name='cashier-confirm'),
    
    # Services
    path('services/', views.ServiceListView.as_view(), name='service-list'),

    # Pricing
    path('pricing/',          views.PricingRuleListView.as_view(), name='pricing-list'),
    path('price/calculate/',  views.PriceCalculateView.as_view(),  name='price-calculate'),
]