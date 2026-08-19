from django.urls import path

from . import views

urlpatterns = [
    path('machines/',                views.MachineListView.as_view(), name='machine-list'),
    path('machines/<int:pk>/down/',  views.MachineDownView.as_view(), name='machine-down'),
    path('machines/<int:pk>/up/',    views.MachineUpView.as_view(),   name='machine-up'),
]