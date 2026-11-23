from django.urls import path

from apps.partners import views

urlpatterns = [
    path('open/', views.OpenView.as_view(), name='partners-open'),
    path('code/', views.CodeView.as_view(), name='partners-code'),
    path('apply/', views.ApplyView.as_view(), name='partners-apply'),
    path('me/', views.MeView.as_view(), name='partners-me'),
    path('orders/', views.OrderView.as_view(), name='partners-orders'),
]
