from django.contrib import admin
from django.urls import include, path
from rest_framework_simplejwt.views import TokenRefreshView
from apps.accounts.api.views import AuditedTokenObtainPairView
from django.conf import settings
from django.conf.urls.static import static
from config.views import (
    login_view, dashboard_view, inbox_view, jobs_view,
    cashier_view, attendant_view, belt_manager_view, regional_manager_view,
    finance_portal_view, ops_portal_view, finance_ops_portal_view,
)

urlpatterns = [
    # Admin
    path('admin/', admin.site.urls),

    # Auth
    path('api/v1/auth/token/',         AuditedTokenObtainPairView.as_view(), name='token-obtain'),
    path('api/v1/auth/token/refresh/', TokenRefreshView.as_view(),           name='token-refresh'),

    # API v1
    path('api/v1/organization/',  include('apps.organization.api.urls')),
    path('api/v1/accounts/',      include('apps.accounts.api.urls')),
    path('api/v1/customers/',     include('apps.customers.api.urls')),
    path('api/v1/jobs/',          include('apps.jobs.api.urls')),
    path('api/v1/hr/',            include('apps.hr.api.urls')),
    path('api/v1/communications/',include('apps.communications.api.urls')),
    path('api/v1/finance/',       include('apps.finance.api.urls')),
    path('api/v1/notifications/', include('apps.notifications.urls')),
    path('api/v1/analytics/',     include('apps.analytics.api.urls')),
    path('api/v1/inventory/',     include('apps.inventory.api.urls')),
    path('api/v1/procurement/',   include('apps.procurement.api.urls')),

    # Portals
    path('portal/login/',            login_view,              name='login'),
    path('portal/dashboard/',        dashboard_view,          name='dashboard'),
    path('portal/inbox/',            inbox_view,              name='inbox'),
    path('portal/jobs/',             jobs_view,               name='jobs'),
    path('portal/cashier/',          cashier_view,            name='cashier'),
    path('portal/attendant/',        attendant_view,          name='attendant'),
    path('portal/belt-manager/',     belt_manager_view,       name='belt-manager'),
    path('portal/regional-manager/', regional_manager_view,   name='regional-manager'),
    path('portal/finance/',          finance_portal_view,     name='finance-portal'),
    path('portal/ops/',              ops_portal_view,         name='ops-portal'),
    path('portal/finance-ops/',      finance_ops_portal_view, name='finance-ops-portal'),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)