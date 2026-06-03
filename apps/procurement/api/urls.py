from django.urls import path
from apps.procurement.api import views, views_budget


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
    path('orders/<int:pk>/receipt/',        views_budget.ReceiptUploadView.as_view(), name='procurement-receipt-upload'),
    path('orders/<int:pk>/verify-receipt/', views_budget.ReceiptVerifyView.as_view(), name='procurement-receipt-verify'),

    # ── Budget ────────────────────────────────────────────────────────
    path('budgets/',                              views_budget.AnnualBudgetListView.as_view(),    name='budget-list'),
    path('budgets/<int:pk>/',                     views_budget.AnnualBudgetDetailView.as_view(),  name='budget-detail'),
    path('budgets/<int:pk>/approve/',             views_budget.AnnualBudgetApproveView.as_view(), name='budget-approve'),
    path('budgets/<int:pk>/envelopes/',           views_budget.BudgetEnvelopeListView.as_view(),  name='budget-envelopes'),
    path('envelopes/current/',                    views_budget.CurrentEnvelopeView.as_view(),     name='envelope-current'),

    # ── Vendors ───────────────────────────────────────────────────────
    path('vendors/',                              views_budget.VendorListView.as_view(),          name='vendor-list'),
    path('vendors/<int:pk>/',                     views_budget.VendorDetailView.as_view(),        name='vendor-detail'),
    path('vendors/<int:pk>/items/',               views_budget.VendorItemCreateView.as_view(),    name='vendor-item-create'),
]