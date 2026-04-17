from django.urls import path
from apps.procurement.api import views

urlpatterns = [
    # Branch health + prepare
    path('branches/',                              views.BranchDeliveryStatusView.as_view(),  name='procurement-branches'),
    path('branches/<int:branch_id>/prepare/',      views.PrepareDeliverablesView.as_view(),   name='procurement-prepare'),
    path('branches/<int:branch_id>/active-order/', views.ActiveOrderForBranchView.as_view(),  name='procurement-active-order'),

    # Order list
    path('orders/',          views.ReplenishmentOrderListView.as_view(), name='procurement-order-list'),
    path('orders/generate/', views.GenerateOrderView.as_view(),          name='procurement-order-generate'),

    # Pending delivery for BM dashboard
    path('pending-delivery/', views.PendingDeliveryForBranchView.as_view(), name='procurement-pending-delivery'),

    # Order detail
    path('orders/<int:pk>/', views.ReplenishmentOrderDetailView.as_view(), name='procurement-order-detail'),

    # Lifecycle transitions
    path('orders/<int:pk>/confirm/',        views.ConfirmOrderView.as_view(),         name='procurement-confirm'),
    path('orders/<int:pk>/submit-finance/', views.SubmitToFinanceView.as_view(),      name='procurement-submit-finance'),
    path('orders/<int:pk>/approve/',        views.ApproveOrderView.as_view(),         name='procurement-approve'),
    path('orders/<int:pk>/reject/',         views.RejectOrderView.as_view(),          name='procurement-reject'),
    path('orders/<int:pk>/dispatch/',       views.DispatchOrderView.as_view(),        name='procurement-dispatch'),
    path('orders/<int:pk>/deliver/',        views.RecordDeliveryView.as_view(),       name='procurement-deliver'),
    path('orders/<int:pk>/accept/',         views.AcceptDeliveryView.as_view(),       name='procurement-accept'),
    path('orders/<int:pk>/cancel/',         views.CancelOrderView.as_view(),          name='procurement-cancel'),
]