from django.contrib import admin
from apps.finance.models import (
    DailySalesSheet, CashierFloat, PettyCash,
    POSTransaction, Receipt,
    CreditAccount, CreditPayment, BranchTransferCredit,
    Invoice, InvoiceLineItem,
)


class InvoiceLineItemInline(admin.TabularInline):
    model         = InvoiceLineItem
    extra         = 0
    readonly_fields = ['line_total', 'created_at']
    fields        = [
        'service', 'label', 'quantity', 'pages', 'sets',
        'is_color', 'paper_size', 'sides',
        'unit_price', 'line_total', 'position',
    ]


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display  = [
        'invoice_number', 'branch', 'invoice_type', 'status',
        'bill_to_name', 'bill_to_company',
        'subtotal', 'vat_amount', 'total',
        'delivery_channel', 'sent_at', 'generated_by',
        'created_at',
    ]
    list_filter   = ['invoice_type', 'status', 'delivery_channel', 'branch']
    search_fields = [
        'invoice_number', 'bill_to_name',
        'bill_to_email', 'bill_to_company',
    ]
    readonly_fields = [
        'invoice_number', 'subtotal', 'vat_amount', 'total',
        'sent_at', 'pdf_path', 'created_at', 'updated_at',
    ]
    inlines = [InvoiceLineItemInline]


@admin.register(InvoiceLineItem)
class InvoiceLineItemAdmin(admin.ModelAdmin):
    list_display  = ['invoice', 'label', 'quantity', 'pages', 'sets', 'unit_price', 'line_total']
    list_filter   = ['is_color', 'paper_size']
    readonly_fields = ['line_total', 'created_at', 'updated_at']