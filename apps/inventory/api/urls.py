from django.urls import path
from .views import (
    BranchStockListView,
    StockMovementListView,
    WasteIncidentListView,
    ReceiveStockView,
    WasteIncidentCreateView,
    BranchEquipmentListView,
    BranchEquipmentDetailView,
    MaintenanceLogListView,
    EquipmentQRView,
)
urlpatterns = [
    path('stock/',                                    BranchStockListView.as_view(),      name='inventory-stock'),
    path('stock/receive/',                            ReceiveStockView.as_view(),          name='inventory-receive'),
    path('movements/',                                StockMovementListView.as_view(),     name='inventory-movements'),
    path('waste/',                                    WasteIncidentListView.as_view(),     name='inventory-waste-list'),
    path('waste/report/',                             WasteIncidentCreateView.as_view(),   name='inventory-waste-create'),
    path('equipment/',                                BranchEquipmentListView.as_view(),   name='inventory-equipment-list'),
    path('equipment/<int:pk>/',                       BranchEquipmentDetailView.as_view(), name='inventory-equipment-detail'),
    path('equipment/<int:pk>/maintenance/',           MaintenanceLogListView.as_view(),    name='inventory-maintenance-list'),
    path('equipment/<int:pk>/qr/',                    EquipmentQRView.as_view(),           name='inventory-equipment-qr'),
]