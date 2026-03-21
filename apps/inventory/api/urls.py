from django.urls import path
from .views import (
    BranchStockListView,
    StockMovementListView,
    WasteIncidentListView,
    ReceiveStockView,
    WasteIncidentCreateView,
)

urlpatterns = [
    path('stock/',          BranchStockListView.as_view(),     name='inventory-stock'),
    path('stock/receive/',  ReceiveStockView.as_view(),         name='inventory-receive'),
    path('movements/',      StockMovementListView.as_view(),    name='inventory-movements'),
    path('waste/',          WasteIncidentListView.as_view(),    name='inventory-waste-list'),
    path('waste/report/',   WasteIncidentCreateView.as_view(),  name='inventory-waste-create'),
]