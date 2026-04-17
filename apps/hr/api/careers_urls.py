from django.urls import path
from apps.hr.api.views import (
    PublicVacancyListView,
    PublicVacancyDetailView,
    PublicApplyView,
    PublicOnboardingFormView,
)

urlpatterns = [
    path("vacancies/",              PublicVacancyListView.as_view(),    name="public-vacancy-list"),
    path("vacancies/<int:pk>/",     PublicVacancyDetailView.as_view(),  name="public-vacancy-detail"),
    path("apply/",                  PublicApplyView.as_view(),          name="public-apply"),
    path("onboarding/<str:token>/", PublicOnboardingFormView.as_view(), name="public-onboarding"),
]