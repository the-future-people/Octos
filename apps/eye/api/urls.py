from django.urls import path

from . import views

urlpatterns = [
    path('me/',                 views.MeView.as_view(),        name='eye-me'),
    path('tree/',               views.TreeView.as_view(),      name='eye-tree'),
    path('overview/',           views.OverviewView.as_view(),  name='eye-overview'),
    path('people/',             views.PeopleView.as_view(),    name='eye-people'),
    path('people/<int:pk>/',    views.PersonView.as_view(),    name='eye-person'),
    path('money/',              views.MoneyView.as_view(),     name='eye-money'),
    path('jobs/',               views.JobsView.as_view(),      name='eye-jobs'),
    path('jobs/<int:pk>/',      views.JobView.as_view(),       name='eye-job'),
    path('machines/',           views.MachinesView.as_view(),  name='eye-machines'),
    path('machines/<int:pk>/',  views.MachineView.as_view(),   name='eye-machine'),
    path('inventory/',          views.InventoryView.as_view(), name='eye-inventory'),
    path('customers/',          views.CustomersView.as_view(), name='eye-customers'),
    path('customers/<int:pk>/', views.CustomerView.as_view(),  name='eye-customer'),
    path('online/',             views.OnlineView.as_view(),    name='eye-online'),
    path('app/',                views.AppView.as_view(),       name='eye-app'),
    path('health/',             views.HealthView.as_view(),    name='eye-health'),
]
