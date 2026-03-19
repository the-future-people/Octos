from django.urls import path
from .views import (
    BranchLockStatusView,
    DailySalesSheetListView,
    DailySalesSheetDetailView,
    DailySalesSheetTodayView,
    DailySalesSheetNotesView,
    DailySalesSheetCloseView,
    CashierFloatSetView,
    CashierFloatCloseView,
    EODSummaryView,
    PettyCashCreateView,
    POSTransactionListView,
    POSTransactionSettleView,
    ReceiptDetailView,
    ReceiptSendWhatsAppView,
    ReceiptThermalView,
    CreditAccountListView,
    CreditAccountDetailView,
    CreditAccountCreateView,
    CreditAccountApproveView,
    CreditSettlementView,
    BranchTransferCreditListView,
    BranchTransferCreditReconcileView,
    DailySalesSheetPDFView,
    CashierSignOffView,
    CashierShiftStatusView,
    CashierSignOffView,
    CashierShiftStatusView,
    InvoiceListView,
    InvoiceDetailView,
    InvoiceCreateView,
    InvoiceSendView,
    InvoicePDFView,
)

urlpatterns = [
    # ── Daily Sales Sheet ─────────────────────────────────────
    path('sheets/',                         DailySalesSheetListView.as_view(),    name='sheet-list'),
    path('sheets/today/',                   DailySalesSheetTodayView.as_view(),   name='sheet-today'),
    path('sheets/<int:pk>/',                DailySalesSheetDetailView.as_view(),  name='sheet-detail'),
    path('sheets/<int:pk>/notes/',          DailySalesSheetNotesView.as_view(),   name='sheet-notes'),
    path('sheets/<int:pk>/close/',          DailySalesSheetCloseView.as_view(),   name='sheet-close'),
    path('sheets/<int:pk>/floats/set/',     CashierFloatSetView.as_view(),        name='float-set'),
    path('sheets/<int:pk>/petty-cash/',     PettyCashCreateView.as_view(),        name='petty-cash-create'),

    # ── Cashier Float ─────────────────────────────────────────
    path('floats/<int:pk>/close/',          CashierFloatCloseView.as_view(),      name='float-close'),

    # ── POS Transactions ──────────────────────────────────────
    path('pos/',                            POSTransactionListView.as_view(),     name='pos-list'),
    path('pos/<int:pk>/settle/',            POSTransactionSettleView.as_view(),   name='pos-settle'),

    # ── Receipts ──────────────────────────────────────────────
    path('receipts/<int:pk>/',              ReceiptDetailView.as_view(),          name='receipt-detail'),
    path('receipts/<int:pk>/send-whatsapp/', ReceiptSendWhatsAppView.as_view(),   name='receipt-whatsapp'),
    path('receipts/<int:pk>/thermal/',      ReceiptThermalView.as_view(),         name='receipt-thermal'),

    # ── Credit Accounts ───────────────────────────────────────
    path('credit/',                         CreditAccountListView.as_view(),      name='credit-list'),
    path('credit/create/',                  CreditAccountCreateView.as_view(),    name='credit-create'),
    path('credit/<int:pk>/',                CreditAccountDetailView.as_view(),    name='credit-detail'),
    path('credit/<int:pk>/approve/',        CreditAccountApproveView.as_view(),   name='credit-approve'),
    path('credit/<int:pk>/settle/',         CreditSettlementView.as_view(),       name='credit-settle'),

    # ── Branch Transfer Credits ───────────────────────────────
    path('transfers/',                      BranchTransferCreditListView.as_view(),       name='transfer-list'),
    path('transfers/<int:pk>/reconcile/',   BranchTransferCreditReconcileView.as_view(),  name='transfer-reconcile'),
    path('sheets/<int:pk>/pdf/', DailySalesSheetPDFView.as_view(), name='sheet-pdf'),
    path('lock-status/',                    BranchLockStatusView.as_view(),       name='branch-lock-status'),
    path('floats/<int:pk>/sign-off/',       CashierSignOffView.as_view(),         name='float-sign-off'),
    path('cashier/shift-status/',           CashierShiftStatusView.as_view(),     name='cashier-shift-status'),
    # ── Invoices ──────────────────────────────────────────────
    path('invoices/',                       InvoiceListView.as_view(),            name='invoice-list'),
    path('invoices/create/',                InvoiceCreateView.as_view(),          name='invoice-create'),
    path('invoices/<int:pk>/',              InvoiceDetailView.as_view(),          name='invoice-detail'),
    path('invoices/<int:pk>/send/',         InvoiceSendView.as_view(),            name='invoice-send'),
    path('invoices/<int:pk>/pdf/',          InvoicePDFView.as_view(),             name='invoice-pdf'),
    path('sheets/<int:pk>/eod-summary/', EODSummaryView.as_view(), name='sheet-eod-summary'),
]