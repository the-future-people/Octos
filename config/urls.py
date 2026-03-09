from django.contrib import admin
from django.urls import path, include
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

urlpatterns = [
    # Admin
    path('admin/', admin.site.urls),

    # Auth
    path('api/v1/auth/token/', TokenObtainPairView.as_view(), name='token-obtain'),
    path('api/v1/auth/token/refresh/', TokenRefreshView.as_view(), name='token-refresh'),

    # API v1
    path('api/v1/organization/', include('apps.organization.api.urls')),
    path('api/v1/accounts/', include('apps.accounts.api.urls')),
    path('api/v1/customers/', include('apps.customers.api.urls')),
    path('api/v1/jobs/', include('apps.jobs.api.urls')),
    path('api/v1/hr/', include('apps.hr.api.urls')),
]
