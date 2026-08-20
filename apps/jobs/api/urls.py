from django.urls import path
from . import views
from . import proforma_views
from . import coordinator_views
from . import file_views
from .views import BranchPerformanceView, JobHistoryView, JobStatsView, LateJobView, ResolveHandoverView, ServiceListView, ServicePerformanceView

urlpatterns = [
    # Jobs CRUD
    path('',        views.JobListView.as_view(),   name='job-list'),
    path('create/', views.JobCreateView.as_view(), name='job-create'),
    path('<int:pk>/', views.JobDetailView.as_view(), name='job-detail'),

    # Job actions
    path('<int:pk>/transition/', views.JobTransitionView.as_view(),  name='job-transition'),
    path('<int:pk>/files/',      views.JobFileUploadView.as_view(),  name='job-file-upload'),

        # Files. MEDIA_URL points here, so file.url resolves to this view
    # rather than to a path served straight off disk.
    path('files/<int:pk>/', file_views.JobFileDownloadView.as_view(), name='job-file'),

    # Coordinator
    path('coordinator/verification-queue/', coordinator_views.VerificationQueueView.as_view(), name='verification-queue'),
    path('coordinator/board/',              coordinator_views.ProductionBoardView.as_view(),   name='production-board'),
    path('coordinator/suspended/',          coordinator_views.SuspendedJobsView.as_view(),     name='suspended-jobs'),
    path('<int:pk>/verify/',                coordinator_views.VerifyJobView.as_view(),         name='job-verify'),
    path('<int:pk>/verify/reject/',         coordinator_views.RejectVerificationView.as_view(), name='job-verify-reject'),
    path('<int:pk>/verify/suspend/',        coordinator_views.SuspendJobView.as_view(),        name='job-verify-suspend'),

    # Lifecycle axes
    path('<int:pk>/move/',   views.JobAxisMoveView.as_view(), name='job-axis-move'),
    path('<int:pk>/halt/',   views.JobHaltView.as_view(),     name='job-halt'),
    path('<int:pk>/resume/', views.JobResumeView.as_view(),   name='job-resume'),

    # Proformas
    path('proformas/',                  proforma_views.ProformaListView.as_view(),    name='proforma-list'),
    path('proformas/create/',           proforma_views.ProformaCreateView.as_view(),  name='proforma-create'),
    path('proformas/<int:pk>/',         proforma_views.ProformaDetailView.as_view(),  name='proforma-detail'),
    path('proformas/<int:pk>/issue/',   proforma_views.ProformaIssueView.as_view(),   name='proforma-issue'),
    path('proformas/<int:pk>/revise/',  proforma_views.ProformaReviseView.as_view(),  name='proforma-revise'),
    path('proformas/<int:pk>/convert/', proforma_views.ProformaConvertView.as_view(), name='proforma-convert'),
    path('proformas/<int:pk>/pdf/',     proforma_views.ProformaPDFView.as_view(),     name='proforma-pdf'),

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
    path('pricing/',          views.PricingRuleListView.as_view(),   name='pricing-list'),
    path('pricing/create/',   views.PricingRuleCreateView.as_view(), name='pricing-create'),
    path('pricing/<int:pk>/', views.PricingRuleDetailView.as_view(), name='pricing-detail'),
    path('pricing/<int:pk>/', views.PricingRuleDetailView.as_view(), name='pricing-detail'),
    path('price/bulk/',       views.PriceBulkView.as_view(),       name='price-bulk'),
    path('price/calculate/',  views.PriceCalculateView.as_view(),  name='price-calculate'),
    # Drafts
    path('drafts/',              views.DraftListView.as_view(),   name='draft-list'),
    path('drafts/save/',         views.SaveDraftView.as_view(),   name='draft-save'),
    path('drafts/<int:pk>/discard/', views.DiscardDraftView.as_view(), name='draft-discard'),
    path('reports/services/', views.ServicePerformanceView.as_view(), name='service-performance'),
    path('stats/',            views.JobStatsView.as_view(),           name='job-stats'),
    path('workload/',         views.ActiveWorkloadView.as_view(),     name='job-workload'),
    path('performance/',      views.BranchPerformanceView.as_view(),  name='branch-performance'),
    path('history/', views.JobHistoryView.as_view(), name='job-history'),
    path('services/',        views.ServiceListView.as_view(),   name='service-list'),
    path('services/create/', views.ServiceCreateView.as_view(), name='service-create'),
    path('late/', views.LateJobView.as_view(), name='late-job'),
    path('intake-held/', views.IntakeHeldQueueView.as_view(), name='intake-held-queue'),
    path('<int:pk>/resolve-handover/', views.ResolveHandoverView.as_view(), name='resolve-handover'),
    path('<int:pk>/dispute-handover/', views.DisputeHandoverView.as_view(), name='dispute-handover'),
]