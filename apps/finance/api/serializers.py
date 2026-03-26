from rest_framework import serializers
from apps.finance.models import (
    DailySalesSheet,
    CashierFloat,
    PettyCash,
    POSTransaction,
    Receipt,
    CreditAccount,
    CreditPayment,
    BranchTransferCredit,
    Invoice,
    InvoiceLineItem,
)
from apps.finance.models import (
    DailySalesSheet,
    WeeklyReport
)


# ─────────────────────────────────────────────────────────────────────────────
# Daily Sales Sheet
# ─────────────────────────────────────────────────────────────────────────────

class DailySalesSheetListSerializer(serializers.ModelSerializer):
    branch_name  = serializers.CharField(source='branch.name', read_only=True)
    branch_code  = serializers.CharField(source='branch.code', read_only=True)
    opened_by_name = serializers.SerializerMethodField()
    closed_by_name = serializers.SerializerMethodField()

    class Meta:
        model  = DailySalesSheet
        fields = [
            'id', 'branch', 'branch_name', 'branch_code',
            'date', 'status',
            'opened_by_name', 'opened_at',
            'closed_by_name', 'closed_at',
            'is_public_holiday', 'public_holiday_name',
            'total_jobs_created', 'total_fresh_revenue',
            'total_deposits', 'total_balances',
            'total_cash', 'total_momo', 'total_pos',
            'total_credit_issued', 'total_credit_settled', 'total_refunds',
            'total_damages', 'total_petty_cash_out',
            'net_cash_in_till', 'vat_collected',
            'notes', 'created_at',
        ]

    def get_opened_by_name(self, obj) -> str:
        if obj.opened_by:
            return obj.opened_by.full_name
        return 'System'

    def get_closed_by_name(self, obj) -> str:
        if obj.closed_by:
            return obj.closed_by.full_name
        if obj.status == DailySalesSheet.Status.AUTO_CLOSED:
            return 'Auto-closed'
        return ''


class DailySalesSheetDetailSerializer(DailySalesSheetListSerializer):
    cashier_floats  = serializers.SerializerMethodField()
    petty_cash      = serializers.SerializerMethodField()
    pending_count   = serializers.SerializerMethodField()

    class Meta(DailySalesSheetListSerializer.Meta):
        fields = DailySalesSheetListSerializer.Meta.fields + [
            'cashier_floats',
            'petty_cash',
            'pending_count',
        ]

    def get_cashier_floats(self, obj) -> list:
        floats = obj.cashier_floats.select_related('cashier', 'signed_off_by')
        return CashierFloatSerializer(floats, many=True).data

    def get_petty_cash(self, obj) -> list:
        entries = obj.petty_cash_entries.select_related('recorded_by', 'approved_by')
        return PettyCashSerializer(entries, many=True).data

    def get_pending_count(self, obj) -> int:
        from apps.jobs.models import Job
        return Job.objects.filter(
            daily_sheet=obj,
            status=Job.PENDING_PAYMENT,
        ).count()


class DailySalesSheetNotesSerializer(serializers.ModelSerializer):
    """BM can only update notes — nothing else."""

    class Meta:
        model  = DailySalesSheet
        fields = ['notes']


# ─────────────────────────────────────────────────────────────────────────────
# Cashier Float
# ─────────────────────────────────────────────────────────────────────────────

class CashierFloatSerializer(serializers.ModelSerializer):
    cashier_name     = serializers.CharField(source='cashier.full_name', read_only=True)
    signed_off_by_name = serializers.SerializerMethodField()

    class Meta:
        model  = CashierFloat
        fields = [
            'id', 'cashier', 'cashier_name',
            'opening_float', 'closing_cash',
            'expected_cash', 'variance', 'variance_notes',
            'is_signed_off', 'signed_off_by_name', 'signed_off_at',
            'created_at',
        ]
        read_only_fields = [
            'expected_cash', 'variance',
            'is_signed_off', 'signed_off_at',
        ]

    def get_signed_off_by_name(self, obj) -> str:
        if obj.signed_off_by:
            return obj.signed_off_by.full_name
        return ''


class CashierFloatSetSerializer(serializers.Serializer):
    """BM sets the opening float for a cashier."""
    cashier_id    = serializers.IntegerField()
    opening_float = serializers.DecimalField(max_digits=10, decimal_places=2)


class CashierFloatCloseSerializer(serializers.Serializer):
    """Cashier submits closing cash count."""
    closing_cash   = serializers.DecimalField(max_digits=10, decimal_places=2)
    variance_notes = serializers.CharField(required=False, allow_blank=True)


# ─────────────────────────────────────────────────────────────────────────────
# Petty Cash
# ─────────────────────────────────────────────────────────────────────────────

class PettyCashSerializer(serializers.ModelSerializer):
    recorded_by_name = serializers.CharField(
        source='recorded_by.full_name', read_only=True
    )
    approved_by_name = serializers.CharField(
        source='approved_by.full_name', read_only=True
    )

    class Meta:
        model  = PettyCash
        fields = [
            'id', 'amount', 'category', 'purpose',
            'recorded_by_name', 'approved_by_name', 'approved_at',
            'is_correction', 'corrects_entry',
            'created_at',
        ]


class PettyCashCreateSerializer(serializers.Serializer):
    """Cashier records a petty cash disbursement."""
    cashier_float_id = serializers.IntegerField()
    amount           = serializers.DecimalField(max_digits=10, decimal_places=2)
    category         = serializers.ChoiceField(choices=PettyCash.Category.choices)
    purpose          = serializers.CharField()


# ─────────────────────────────────────────────────────────────────────────────
# POS Transaction
# ─────────────────────────────────────────────────────────────────────────────

class POSTransactionSerializer(serializers.ModelSerializer):
    cashier_name = serializers.CharField(source='cashier.full_name', read_only=True)

    class Meta:
        model  = POSTransaction
        fields = [
            'id', 'job', 'amount', 'approval_code',
            'terminal_id', 'status',
            'collected_date', 'settlement_date',
            'cashier_name', 'reversal_notes',
            'created_at',
        ]


class POSSettleSerializer(serializers.Serializer):
    """Mark a POS transaction as settled."""
    settlement_date = serializers.DateField()


# ─────────────────────────────────────────────────────────────────────────────
# Receipt
# ─────────────────────────────────────────────────────────────────────────────

class ReceiptSerializer(serializers.ModelSerializer):
    cashier_name = serializers.CharField(source='cashier.full_name', read_only=True)
    job_number   = serializers.CharField(source='job.job_number', read_only=True)

    class Meta:
        model  = Receipt
        fields = [
            'id', 'receipt_number', 'job', 'job_number',
            'cashier_name', 'payment_method',
            'amount_paid', 'balance_due',
            'momo_reference', 'pos_approval_code',
            'customer_name', 'customer_phone', 'company_name',
            'subtotal', 'vat_rate', 'vat_amount',
            'nhil_amount', 'getfund_amount',
            'whatsapp_status', 'whatsapp_sent_at',
            'print_status', 'printed_at',
            'is_void', 'created_at',
        ]


# ─────────────────────────────────────────────────────────────────────────────
# Credit Account
# ─────────────────────────────────────────────────────────────────────────────

class CreditAccountSerializer(serializers.ModelSerializer):
    customer_name    = serializers.CharField(
        source='customer.full_name', read_only=True
    )
    recommended_by_name = serializers.CharField(
        source='recommended_by.full_name', read_only=True
    )
    approved_by_name = serializers.CharField(
        source='approved_by.full_name', read_only=True
    )
    available_credit = serializers.FloatField(read_only=True)
    is_over_limit    = serializers.BooleanField(read_only=True)

    class Meta:
        model  = CreditAccount
        fields = [
            'id', 'customer', 'customer_name',
            'account_type', 'status',
            'credit_limit', 'current_balance',
            'available_credit', 'is_over_limit',
            'payment_terms',
            'organisation_name', 'contact_person', 'contact_phone',
            'recommended_by_name', 'approved_by_name', 'approved_at',
            'suspended_at', 'suspension_reason',
            'notes', 'created_at',
        ]


class CreditAccountCreateSerializer(serializers.Serializer):
    """BM recommends a credit account — Belt Manager approves separately."""
    customer_id       = serializers.IntegerField()
    account_type      = serializers.ChoiceField(
        choices=CreditAccount.AccountType.choices
    )
    credit_limit      = serializers.DecimalField(max_digits=10, decimal_places=2)
    payment_terms     = serializers.IntegerField(default=30)
    organisation_name = serializers.CharField(required=False, allow_blank=True)
    contact_person    = serializers.CharField(required=False, allow_blank=True)
    contact_phone     = serializers.CharField(required=False, allow_blank=True)
    notes             = serializers.CharField(required=False, allow_blank=True)


class CreditAccountApproveSerializer(serializers.Serializer):
    """Belt Manager approves or rejects a recommended credit account."""
    approved = serializers.BooleanField()
    notes    = serializers.CharField(required=False, allow_blank=True)


# ─────────────────────────────────────────────────────────────────────────────
# Credit Payment
# ─────────────────────────────────────────────────────────────────────────────

class CreditPaymentSerializer(serializers.ModelSerializer):
    received_by_name = serializers.CharField(
        source='received_by.full_name', read_only=True
    )
    customer_name    = serializers.CharField(
        source='credit_account.customer.full_name', read_only=True
    )

    class Meta:
        model  = CreditPayment
        fields = [
            'id', 'credit_account', 'customer_name',
            'amount', 'payment_method',
            'momo_reference', 'pos_approval_code',
            'balance_before', 'balance_after',
            'received_by_name', 'notes', 'created_at',
        ]


class CreditSettlementSerializer(serializers.Serializer):
    """Cashier records a credit settlement payment."""
    amount            = serializers.DecimalField(max_digits=10, decimal_places=2)
    payment_method    = serializers.ChoiceField(
        choices=[('CASH', 'Cash'), ('MOMO', 'Mobile Money'), ('POS', 'POS')]
    )
    momo_reference    = serializers.CharField(required=False, allow_blank=True)
    pos_approval_code = serializers.CharField(required=False, allow_blank=True)
    notes             = serializers.CharField(required=False, allow_blank=True)


# ─────────────────────────────────────────────────────────────────────────────
# Branch Transfer Credit
# ─────────────────────────────────────────────────────────────────────────────

class BranchTransferCreditSerializer(serializers.ModelSerializer):
    origin_name      = serializers.CharField(
        source='origin_branch.name', read_only=True
    )
    destination_name = serializers.CharField(
        source='destination_branch.name', read_only=True
    )
    job_number       = serializers.CharField(
        source='job.job_number', read_only=True
    )
    reconciled_by_name = serializers.SerializerMethodField()

    class Meta:
        model  = BranchTransferCredit
        fields = [
            'id', 'job', 'job_number',
            'origin_branch', 'origin_name',
            'destination_branch', 'destination_name',
            'job_value', 'amount_collected',
            'status', 'system_reason',
            'reconciled_by_name', 'reconciled_at',
            'reconciliation_notes', 'created_at',
        ]

    def get_reconciled_by_name(self, obj) -> str:
        if obj.reconciled_by:
            return obj.reconciled_by.full_name
        return ''
    
# ─────────────────────────────────────────────────────────────────────────────
# Cashier Sign-Off
# ─────────────────────────────────────────────────────────────────────────────

class CashierSignOffSerializer(serializers.Serializer):
    """Cashier submits full sign-off at end of shift."""
    closing_cash      = serializers.DecimalField(max_digits=10, decimal_places=2)
    variance_notes    = serializers.CharField(allow_blank=True, default='')
    shift_notes       = serializers.CharField(allow_blank=True, default='')

    # Overtime
    is_overtime       = serializers.BooleanField(default=False)
    overtime_reason   = serializers.CharField(allow_blank=True, default='')
    overtime_until    = serializers.DateTimeField(required=False, allow_null=True)

    # Cover
    is_cover          = serializers.BooleanField(default=False)
    covering_for_id   = serializers.IntegerField(required=False, allow_null=True)
    cover_until       = serializers.DateTimeField(required=False, allow_null=True)

    def validate(self, data):
        if data.get('is_overtime') and not data.get('overtime_reason'):
            raise serializers.ValidationError(
                {'overtime_reason': 'Reason is required for overtime.'}
            )
        if data.get('is_overtime') and not data.get('overtime_until'):
            raise serializers.ValidationError(
                {'overtime_until': 'End time is required for overtime.'}
            )
        if data.get('is_cover') and not data.get('covering_for_id'):
            raise serializers.ValidationError(
                {'covering_for_id': 'Must specify who you are covering.'}
            )
        if data.get('is_cover') and not data.get('cover_until'):
            raise serializers.ValidationError(
                {'cover_until': 'End time is required for cover shift.'}
            )
        return data


class ShiftStatusSerializer(serializers.Serializer):
    """Read-only — returned by GET /api/v1/finance/cashier/shift-status/"""
    has_shift         = serializers.BooleanField()
    shift_end         = serializers.TimeField(allow_null=True)
    minutes_remaining = serializers.IntegerField(allow_null=True)
    should_prompt     = serializers.BooleanField()   # ≤60 min remaining
    should_lock       = serializers.BooleanField()   # shift end passed
    is_signed_off     = serializers.BooleanField()
    float_id          = serializers.IntegerField(allow_null=True)
    is_overtime       = serializers.BooleanField()
    overtime_until    = serializers.DateTimeField(allow_null=True)
    is_cover          = serializers.BooleanField()
    cover_until       = serializers.DateTimeField(allow_null=True)


# ─────────────────────────────────────────────────────────────────────────────
# Invoice
# ─────────────────────────────────────────────────────────────────────────────

class InvoiceLineItemSerializer(serializers.ModelSerializer):
    service_name = serializers.CharField(source='service.name', read_only=True)

    class Meta:
        model  = InvoiceLineItem
        fields = [
            'id', 'service', 'service_name', 'label',
            'quantity', 'pages', 'sets', 'is_color',
            'paper_size', 'sides',
            'unit_price', 'line_total', 'position',
        ]


class InvoiceSerializer(serializers.ModelSerializer):
    line_items       = InvoiceLineItemSerializer(many=True, read_only=True)
    generated_by_name = serializers.CharField(
        source='generated_by.full_name', read_only=True
    )
    branch_name      = serializers.CharField(source='branch.name',     read_only=True)
    job_number       = serializers.CharField(source='job.job_number',  read_only=True)

    class Meta:
        model  = Invoice
        fields = [
            'id', 'invoice_number', 'invoice_type', 'status',
            'branch', 'branch_name',
            'job', 'job_number',
            'issue_date', 'due_date', 'bm_note',
            'bill_to_name', 'bill_to_phone',
            'bill_to_email', 'bill_to_company',
            'delivery_channel',
            'subtotal', 'vat_rate', 'vat_amount', 'total',
            'sent_at', 'pdf_path',
            'generated_by_name',
            'line_items',
            'created_at',
        ]


class InvoiceCreateSerializer(serializers.Serializer):
    """Create an invoice — job-linked or standalone."""

    # Optional job link
    job_id           = serializers.IntegerField(required=False, allow_null=True)

    # Invoice meta
    invoice_type     = serializers.ChoiceField(
        choices=Invoice.TYPE_CHOICES, default=Invoice.PROFORMA
    )
    due_date         = serializers.DateField(required=False, allow_null=True)
    bm_note          = serializers.CharField(required=False, allow_blank=True, default='')

    # Bill To
    bill_to_name     = serializers.CharField()
    bill_to_phone    = serializers.CharField(required=False, allow_blank=True, default='')
    bill_to_email    = serializers.EmailField(required=False, allow_blank=True, default='')
    bill_to_company  = serializers.CharField(required=False, allow_blank=True, default='')

    # Delivery
    delivery_channel = serializers.ChoiceField(choices=Invoice.DELIVERY_CHOICES)

    # VAT
    vat_rate         = serializers.DecimalField(
        max_digits=5, decimal_places=2, default=0
    )

    # Line items (for standalone — ignored if job_id provided)
    line_items       = serializers.ListField(
        child=serializers.DictField(), required=False, default=list
    )

    def validate(self, data):
        # Must have either a job or line items
        if not data.get('job_id') and not data.get('line_items'):
            raise serializers.ValidationError(
                'Provide either a job_id or at least one line item.'
            )
        # WhatsApp needs phone
        channel = data.get('delivery_channel')
        if channel in ['WHATSAPP', 'BOTH'] and not data.get('bill_to_phone'):
            raise serializers.ValidationError(
                {'bill_to_phone': 'Phone number required for WhatsApp delivery.'}
            )
        # Email needs email
        if channel in ['EMAIL', 'BOTH'] and not data.get('bill_to_email'):
            raise serializers.ValidationError(
                {'bill_to_email': 'Email address required for email delivery.'}
            )
        return data

# ─────────────────────────────────────────────────────────────────────────────
# Weekly Report
# ─────────────────────────────────────────────────────────────────────────────

from apps.finance.models import WeeklyReport

class WeeklyReportListSerializer(serializers.ModelSerializer):
    branch_name      = serializers.CharField(source='branch.name', read_only=True)
    branch_code      = serializers.CharField(source='branch.code', read_only=True)
    submitted_by_name = serializers.SerializerMethodField()
    total_collected  = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )
    sheets_count     = serializers.IntegerField(read_only=True)
    all_sheets_closed = serializers.BooleanField(read_only=True)

    class Meta:
        model  = WeeklyReport
        fields = [
            'id', 'branch', 'branch_name', 'branch_code',
            'week_number', 'year', 'date_from', 'date_to',
            'status',
            'total_cash', 'total_momo', 'total_pos',
            'total_collected', 'total_petty_cash_out',
            'total_jobs_created', 'total_jobs_complete',
            'total_jobs_cancelled', 'carry_forward_count',
            'sheets_count', 'all_sheets_closed',
            'submitted_by_name', 'submitted_at',
            'bm_notes', 'pdf_path', 'created_at',
        ]

    def get_submitted_by_name(self, obj) -> str:
        if obj.submitted_by:
            return obj.submitted_by.full_name
        return ''


class WeeklyReportDetailSerializer(WeeklyReportListSerializer):
    daily_sheets     = serializers.SerializerMethodField()
    inventory_snapshot = serializers.JSONField(read_only=True)

    class Meta(WeeklyReportListSerializer.Meta):
        fields = WeeklyReportListSerializer.Meta.fields + [
            'daily_sheets',
            'inventory_snapshot',
        ]

    def get_daily_sheets(self, obj) -> list:
        sheets = obj.daily_sheets.all().order_by('date')
        return DailySalesSheetListSerializer(sheets, many=True).data


class WeeklyReportNotesSerializer(serializers.Serializer):
    """BM adds or updates notes on a weekly report."""
    bm_notes = serializers.CharField(allow_blank=True)