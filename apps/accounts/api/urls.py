from django.urls import path
from . import views

urlpatterns = [
    path('me/', views.MeView.as_view(), name='me'),
    path('change-password/', views.ChangePasswordView.as_view(), name='change-password'),
    path('pin/set/', views.SetDownloadPinView.as_view(), name='pin-set'),
    path('pin/verify/', views.VerifyDownloadPinView.as_view(), name='pin-verify'),
    path('users/', views.UserListView.as_view(), name='user-list'),
    path('users/create/', views.UserCreateView.as_view(), name='user-create'),
    path('users/<int:pk>/', views.UserDetailView.as_view(), name='user-detail'),
    path('roles/', views.RoleListView.as_view(), name='role-list'),
    path('roles/dropdown/', views.RoleDropdownView.as_view(), name='role-dropdown'),
    path('permissions/', views.PermissionListView.as_view(), name='permission-list'),
    path('pending-activation/me/', views.PendingActivationMeView.as_view(), name='pending-activation-me'),
    path('pending-activation/displacing-me/', views.PendingActivationDisplacingMeView.as_view(), name='pending-activation-displacing-me'),
]