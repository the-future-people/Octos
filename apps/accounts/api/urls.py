from django.urls import path
from . import views

urlpatterns = [
    path('me/', views.MeView.as_view(), name='me'),
    path('change-password/', views.ChangePasswordView.as_view(), name='change-password'),
    path('users/', views.UserListView.as_view(), name='user-list'),
    path('users/create/', views.UserCreateView.as_view(), name='user-create'),
    path('users/<int:pk>/', views.UserDetailView.as_view(), name='user-detail'),
    path('roles/', views.RoleListView.as_view(), name='role-list'),
    path('roles/dropdown/', views.RoleDropdownView.as_view(), name='role-dropdown'),
    path('permissions/', views.PermissionListView.as_view(), name='permission-list'),
]