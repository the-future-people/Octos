from django.urls import path
from . import views

urlpatterns = [
    path('belts/', views.BeltListView.as_view(), name='belt-list'),
    path('regions/', views.RegionListView.as_view(), name='region-list'),
    path('branches/', views.BranchListView.as_view(), name='branch-list'),
    path('branches/dropdown/', views.BranchDropdownView.as_view(), name='branch-dropdown'),
    path('branches/<int:pk>/', views.BranchDetailView.as_view(), name='branch-detail'),
]