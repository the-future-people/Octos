from django.urls import path
from . import views
from .on_shift import OnShiftView
from . import profile_views

urlpatterns = [
    path('me/', views.MeView.as_view(), name='me'),
    path('on-shift/', OnShiftView.as_view(), name='on-shift'),
    path('profile/', profile_views.ProfileView.as_view(), name='profile'),
    path('profile/photo/', profile_views.ProfilePhotoView.as_view(), name='profile-photo'),
    path('staff/', profile_views.StaffListView.as_view(), name='staff-list'),
    path('staff/<int:pk>/', profile_views.StaffMemberView.as_view(), name='staff-member'),
    path('staff/<int:pk>/photo/', profile_views.StaffPhotoView.as_view(), name='staff-photo'),
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
    path('pending-activation/self-activate/', views.SelfActivateView.as_view(), name='self-activate'),
]