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
    CashierSignOffView,
    CashierShiftStatusView,
    CashierHistoryView,
    EODSummaryView,
    PettyCashCreateView,
    POSTransactionListView,
    POSTransactionSettleView,
    ReceiptListView,
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
    InvoiceListView,
    InvoiceDetailView,
    InvoiceCreateView,
    InvoiceSendView,
    InvoicePDFView,
    CashierReceiptListView,
    WeeklyReportListView,
    WeeklyReportDetailView,
    WeeklyReportPrepareView,
    WeeklyReportNotesView,
    WeeklyReportSubmitView,
    WeeklyReportPDFView,
    MonthlyCloseStatusView,
    MonthlyCloseSubmitView,
    MonthlyCloseEndorseView,
    MonthlyCloseRejectView,
    MonthlyClosePDFView,
    MonthlyClosePendingView,
    MonthlyCloseDetailView,
    FloatAcknowledgeView,
    MonthlyCloseDetailView,
    MonthlyCloseMyQueueView,
    MonthlyCloseMyHistoryView,
    MonthlyCloseClearView,
    MonthlyCloseRequestClarificationView,
    MonthlyCloseMyBranchesView
)


urlpatterns = [
    # ── Daily Sales Sheet ─────────────────────────────────────────────────
    path('sheets/',                              DailySalesSheetListView.as_view(),           name='sheet-list'),
    path('sheets/today/',                        DailySalesSheetTodayView.as_view(),          name='sheet-today'),
    path('sheets/<int:pk>/',                     DailySalesSheetDetailView.as_view(),         name='sheet-detail'),
    path('sheets/<int:pk>/notes/',               DailySalesSheetNotesView.as_view(),          name='sheet-notes'),
    path('sheets/<int:pk>/close/',               DailySalesSheetCloseView.as_view(),          name='sheet-close'),
    path('sheets/<int:pk>/floats/set/',          CashierFloatSetView.as_view(),               name='float-set'),
    path('sheets/<int:pk>/petty-cash/',          PettyCashCreateView.as_view(),               name='petty-cash-create'),
    path('sheets/<int:pk>/pdf/',                 DailySalesSheetPDFView.as_view(),            name='sheet-pdf'),
    path('sheets/<int:pk>/eod-summary/',         EODSummaryView.as_view(),                    name='sheet-eod-summary'),

    # ── Cashier Float ─────────────────────────────────────────────────────
    path('floats/<int:pk>/close/',               CashierFloatCloseView.as_view(),             name='float-close'),
    path('floats/<int:pk>/sign-off/',            CashierSignOffView.as_view(),                name='float-sign-off'),

    # ── Cashier ───────────────────────────────────────────────────────────
    path('cashier/shift-status/',                CashierShiftStatusView.as_view(),            name='cashier-shift-status'),
    path('cashier/history/',                     CashierHistoryView.as_view(),                name='cashier-history'),

    # ── POS Transactions ──────────────────────────────────────────────────
    path('pos/',                                 POSTransactionListView.as_view(),            name='pos-list'),
    path('pos/<int:pk>/settle/',                 POSTransactionSettleView.as_view(),          name='pos-settle'),

    # ── Receipts ──────────────────────────────────────────────────────────
    path('receipts/<int:pk>/',                   ReceiptDetailView.as_view(),                 name='receipt-detail'),
    path('receipts/',                       ReceiptListView.as_view(),                        name='receipt-list'),
    path('receipts/<int:pk>/',              ReceiptDetailView.as_view(),                      name='receipt-detail'),
    path('receipts/<int:pk>/send-whatsapp/',     ReceiptSendWhatsAppView.as_view(),           name='receipt-whatsapp'),
    path('receipts/<int:pk>/thermal/',           ReceiptThermalView.as_view(),                name='receipt-thermal'),

    # ── Credit Accounts ───────────────────────────────────────────────────
    path('credit/',                              CreditAccountListView.as_view(),             name='credit-list'),
    path('credit/create/',                       CreditAccountCreateView.as_view(),           name='credit-create'),
    path('credit/<int:pk>/',                     CreditAccountDetailView.as_view(),           name='credit-detail'),
    path('credit/<int:pk>/approve/',             CreditAccountApproveView.as_view(),          name='credit-approve'),
    path('credit/<int:pk>/settle/',              CreditSettlementView.as_view(),              name='credit-settle'),

    # ── Branch Transfer Credits ───────────────────────────────────────────
    path('transfers/',                           BranchTransferCreditListView.as_view(),      name='transfer-list'),
    path('transfers/<int:pk>/reconcile/',        BranchTransferCreditReconcileView.as_view(), name='transfer-reconcile'),

    # ── Lock status ───────────────────────────────────────────────────────
    path('lock-status/',                         BranchLockStatusView.as_view(),              name='branch-lock-status'),

    # ── Invoices ──────────────────────────────────────────────────────────
    path('invoices/',                            InvoiceListView.as_view(),                   name='invoice-list'),
    path('invoices/create/',                     InvoiceCreateView.as_view(),                 name='invoice-create'),
    path('invoices/<int:pk>/',                   InvoiceDetailView.as_view(),                 name='invoice-detail'),
    path('invoices/<int:pk>/send/',              InvoiceSendView.as_view(),                   name='invoice-send'),
    path('invoices/<int:pk>/pdf/',               InvoicePDFView.as_view(),                    name='invoice-pdf'),
    path('cashier/receipts/',                   CashierReceiptListView.as_view(),             name='cashier-receipts'),
    # ── Weekly Report ─────────────────────────────────────────────────────
    path('weekly/',                             WeeklyReportListView.as_view(),               name='weekly-list'),
    path('weekly/prepare/',                     WeeklyReportPrepareView.as_view(),            name='weekly-prepare'),
    path('weekly/<int:pk>/',                    WeeklyReportDetailView.as_view(),             name='weekly-detail'),
    path('weekly/<int:pk>/notes/',              WeeklyReportNotesView.as_view(),              name='weekly-notes'),
    path('weekly/<int:pk>/submit/',             WeeklyReportSubmitView.as_view(),             name='weekly-submit'),
    path('weekly/<int:pk>/pdf/',                WeeklyReportPDFView.as_view(),                name='weekly-pdf'),

    # ── Monthly Close ─────────────────────────────────────────────────────
    path('monthly-close/',                      MonthlyCloseStatusView.as_view(),   name='monthly-close-status'),
    path('monthly-close/submit/',               MonthlyCloseSubmitView.as_view(),   name='monthly-close-submit'),
    path('monthly-close/pending/',              MonthlyClosePendingView.as_view(),  name='monthly-close-pending'),
    path('monthly-close/<int:pk>/endorse/',     MonthlyCloseEndorseView.as_view(),  name='monthly-close-endorse'),
    path('monthly-close/<int:pk>/reject/',      MonthlyCloseRejectView.as_view(),   name='monthly-close-reject'),
    path('monthly-close/<int:pk>/pdf/',         MonthlyClosePDFView.as_view(),      name='monthly-close-pdf'),
    path('monthly-close/<int:pk>/',             MonthlyCloseDetailView.as_view(),   name='monthly-close-detail'),
    path('floats/<int:pk>/acknowledge/',         FloatAcknowledgeView.as_view(),     name='float-acknowledge'),
    path('monthly-close/<int:pk>/',             MonthlyCloseDetailView.as_view(),   name='monthly-close-detail'),

    path('monthly-close/my-queue/',                       MonthlyCloseMyQueueView.as_view(),                  name='monthly-close-my-queue'),
    path('monthly-close/my-history/',                     MonthlyCloseMyHistoryView.as_view(),                name='monthly-close-my-history'),
    path('monthly-close/<int:pk>/clear/',                 MonthlyCloseClearView.as_view(),                    name='monthly-close-clear'),
    path('monthly-close/<int:pk>/request-clarification/', MonthlyCloseRequestClarificationView.as_view(),     name='monthly-close-request-clarification'),
    path('monthly-close/my-branches/', MonthlyCloseMyBranchesView.as_view(), name='monthly-close-my-branches'),
]