from django.contrib import admin
from django.urls import path, include
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from django.conf import settings
from django.conf.urls.static import static
from config.views import login_view, dashboard_view, inbox_view, jobs_view

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
    path('api/v1/communications/', include('apps.communications.api.urls')),
    # Portal
    path('portal/login/', login_view, name='login'),
    path('portal/dashboard/', dashboard_view, name='dashboard'),
    path('portal/inbox/', inbox_view, name='inbox'),
    path('portal/jobs/', jobs_view, name='jobs'),
    path('api/v1/notifications/', include('apps.notifications.urls')),
    path('api/v1/analytics/',     include('apps.analytics.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

