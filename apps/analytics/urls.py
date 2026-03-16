from django.urls import path
from . import views

app_name = 'analytics'

urlpatterns = [
    path('branch/summary/', views.BranchSummaryView.as_view(),       name='branch-summary'),
    path('branch/trend/',   views.BranchSnapshotTrendView.as_view(),  name='branch-trend'),
]