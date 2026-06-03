from django.urls import path
from apps.hr.api.views import (
    ServeCVView,
    VacancyListView,
    VacancyDetailView,
    ApplicationListView,
    ApplicationDetailView,
    ScreenApplicationView,
    InviteToInterviewView,
    SubmitInterviewScoreView,
    DecideApplicationView,
    AcceptOfferView,
    VerifyOnboardingInfoView,
    IssueOfferLetterView,
    RecommendCandidateView,
    AppointCandidateView,
    OnboardingRecordView,
    ConflictCheckView,
)

urlpatterns = [
    # Vacancies
    path('vacancies/',               VacancyListView.as_view(),         name='vacancy-list'),
    path('vacancies/<int:pk>/',      VacancyDetailView.as_view(),       name='vacancy-detail'),

    # Applications
    path('applications/',            ApplicationListView.as_view(),     name='application-list'),
    path('applications/<int:pk>/',   ApplicationDetailView.as_view(),   name='application-detail'),

    # Pipeline actions
    path('applications/<int:pk>/screen/',      ScreenApplicationView.as_view(),    name='application-screen'),
    path('applications/<int:pk>/invite/',      InviteToInterviewView.as_view(),    name='application-invite'),
    path('applications/<int:pk>/interview/',   SubmitInterviewScoreView.as_view(), name='application-interview'),
    path('applications/<int:pk>/decide/',      DecideApplicationView.as_view(),    name='application-decide'),
    path('applications/<int:pk>/accept/',      AcceptOfferView.as_view(),          name='application-accept'),
    path('applications/<int:pk>/verify-info/', VerifyOnboardingInfoView.as_view(), name='application-verify-info'),
    path('applications/<int:pk>/issue-offer/', IssueOfferLetterView.as_view(),     name='application-issue-offer'),
    path('applications/<int:pk>/onboarding/',  OnboardingRecordView.as_view(),     name='application-onboarding'),
    path('applications/<int:pk>/cv/',          ServeCVView.as_view(),              name='application-cv'),

    # Special tracks
    path('recommend/', RecommendCandidateView.as_view(), name='recommend-candidate'),
    path('appoint/',   AppointCandidateView.as_view(),   name='appoint-candidate'),

    # Activation support
    path('conflict-check/', ConflictCheckView.as_view(), name='conflict-check'),
]