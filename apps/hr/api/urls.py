from django.urls import path
from . import views

urlpatterns = [
    # Job Positions
    path('positions/', views.JobPositionListView.as_view(), name='position-list'),
    path('positions/create/', views.JobPositionCreateView.as_view(), name='position-create'),
    path('positions/<int:pk>/', views.JobPositionDetailView.as_view(), name='position-detail'),

    # Applicants
    path('applicants/', views.ApplicantListView.as_view(), name='applicant-list'),
    path('applicants/create/', views.ApplicantCreateView.as_view(), name='applicant-create'),
    path('applicants/<int:pk>/', views.ApplicantDetailView.as_view(), name='applicant-detail'),
    path('applicants/<int:pk>/transition/', views.ApplicantTransitionView.as_view(), name='applicant-transition'),
    path('applicants/<int:pk>/reject/', views.ApplicantRejectView.as_view(), name='applicant-reject'),
    path('applicants/<int:pk>/score/', views.StageScoreCreateView.as_view(), name='applicant-score'),
    path('applicants/<int:pk>/send-offer/', views.ApplicantSendOfferView.as_view(), name='applicant-send-offer'),
    path('applicants/<int:pk>/offer-response/', views.ApplicantOfferResponseView.as_view(), name='applicant-offer-response'),

    # Questionnaires
    path('questionnaires/', views.StageQuestionnaireListView.as_view(), name='questionnaire-list'),

    # Onboarding
    path('onboarding/<int:pk>/', views.OnboardingDetailView.as_view(), name='onboarding-detail'),
    path('onboarding/<int:pk>/update/', views.OnboardingUpdateView.as_view(), name='onboarding-update'),
    path('onboarding/<int:pk>/complete/', views.OnboardingCompleteView.as_view(), name='onboarding-complete'),

    # Employees
    path('employees/', views.EmployeeListView.as_view(), name='employee-list'),
    path('employees/<int:pk>/', views.EmployeeDetailView.as_view(), name='employee-detail'),

    # Payroll
    path('payroll/', views.PayrollListView.as_view(), name='payroll-list'),
    path('payroll/<int:pk>/', views.PayrollDetailView.as_view(), name='payroll-detail'),
]