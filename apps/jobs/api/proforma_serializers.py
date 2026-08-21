"""
Proforma serializers.

Kept separate from serializers.py, which is already large and serves a
different concern — proformas have their own lifecycle and their own rules.
"""

from rest_framework import serializers

from apps.jobs.models import ProformaInvoice


class ProformaLineSerializer(serializers.Serializer):
    """
    One requested line. Deliberately carries no price — pricing is the
    engine's job, and a client-supplied amount on a document that commits
    the branch to a figure is exactly what must not be trusted.
    """
    service     = serializers.IntegerField()
    quantity    = serializers.IntegerField(default=1, min_value=1)
    pages       = serializers.IntegerField(default=1, min_value=1)
    is_color    = serializers.BooleanField(default=False)
    output_mode = serializers.CharField(required=False, allow_null=True, default=None)
    ring_size   = serializers.IntegerField(required=False, allow_null=True, default=None)


class ProformaCreateSerializer(serializers.Serializer):
    customer       = serializers.IntegerField()
    line_items     = ProformaLineSerializer(many=True)
    contact_person = serializers.CharField(required=False, allow_blank=True, default='')
    contact_phone  = serializers.CharField(required=False, allow_blank=True, default='')
    contact_email  = serializers.EmailField(required=False, allow_blank=True, default='')
    notes          = serializers.CharField(required=False, allow_blank=True, default='')

    def validate_line_items(self, value):
        if not value:
            raise serializers.ValidationError('A proforma needs at least one service.')
        return value


class ProformaReviseSerializer(serializers.Serializer):
    """
    A revision replaces the line items wholesale. Partial acceptance is the
    same operation — the manager sends back only what the customer wants.
    """
    line_items = ProformaLineSerializer(many=True)
    notes      = serializers.CharField(required=False, allow_blank=True, default='')

    def validate_line_items(self, value):
        if not value:
            raise serializers.ValidationError('A revision needs at least one service.')
        return value


class ProformaConvertSerializer(serializers.Serializer):
    # Free text rather than a choice list: what was agreed is a commercial
    # note, and the cashier still executes the actual payment through the
    # existing deposit and credit paths.
        # A code the cashier reads as an instruction, not prose. The column is
    # 20 characters deliberately, and an unconstrained CharField let a
    # longer value through DRF for the database to refuse with a 500.
    agreed_terms = serializers.ChoiceField(
        choices=['70', '100', 'CREDIT'],
        required=False, allow_blank=True, default='',
    )


class ProformaListSerializer(serializers.ModelSerializer):
    customer_name = serializers.SerializerMethodField()
    issued_by_name = serializers.SerializerMethodField()
    is_expired     = serializers.BooleanField(read_only=True)
    is_convertible = serializers.BooleanField(read_only=True)
    days_left      = serializers.SerializerMethodField()

    class Meta:
        model  = ProformaInvoice
        fields = [
            'id', 'proforma_number', 'version', 'status',
            'customer', 'customer_name', 'issued_to',
            'total', 'issued_at', 'valid_until', 'days_left',
            'is_expired', 'is_convertible',
            'issued_by', 'issued_by_name', 'job',
            'created_at',
        ]

    def get_customer_name(self, obj):
        return obj.customer.display_name if obj.customer else obj.issued_to

    def get_issued_by_name(self, obj):
        return obj.issued_by.full_name if obj.issued_by else None

    def get_days_left(self, obj):
        """
        Negative means overdue. Drives the follow-up prompt in the UI —
        a proforma nobody chases is just paperwork.
        """
        from django.utils import timezone
        if not obj.valid_until or obj.status != ProformaInvoice.Status.ISSUED:
            return None
        return (obj.valid_until - timezone.localdate()).days


class ProformaDetailSerializer(ProformaListSerializer):
    revision_of   = serializers.SerializerMethodField()
    revised_to    = serializers.SerializerMethodField()
    converted_by_name = serializers.SerializerMethodField()

    class Meta(ProformaListSerializer.Meta):
        fields = ProformaListSerializer.Meta.fields + [
            'line_items', 'subtotal', 'vat_amount', 'nhil_amount',
            'getfund_amount', 'contact_person', 'contact_phone',
            'contact_email', 'notes', 'agreed_terms',
            'converted_at', 'converted_by', 'converted_by_name',
            'revision_of', 'revised_to',
        ]

    def get_converted_by_name(self, obj):
        return obj.converted_by.full_name if obj.converted_by else None

    def get_revision_of(self, obj):
        """The version this one replaced, so the chain can be walked back."""
        if not obj.supersedes_id:
            return None
        prev = obj.supersedes
        return {
            'id'              : prev.id,
            'proforma_number' : prev.proforma_number,
            'version'         : prev.version,
            'total'           : str(prev.total),
        }

    def get_revised_to(self, obj):
        """The version that replaced this one, if any."""
        nxt = getattr(obj, 'superseded_by', None)
        if not nxt:
            return None
        return {
            'id'              : nxt.id,
            'proforma_number' : nxt.proforma_number,
            'version'         : nxt.version,
            'total'           : str(nxt.total),
        }