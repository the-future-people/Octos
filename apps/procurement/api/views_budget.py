# apps/procurement/api/views_budget.py

from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from apps.procurement.models import AnnualBudget, BudgetEnvelope, Vendor, VendorItem
from apps.procurement.services.budget_service import BudgetService
from apps.procurement.api.serializers_budget import (
    AnnualBudgetSerializer,
    AnnualBudgetCreateSerializer,
    VendorSerializer,
    VendorItemSerializer,
)


class AnnualBudgetListView(APIView):
    """
    GET  /api/v1/procurement/budgets/       — list all budgets
    POST /api/v1/procurement/budgets/       — Finance proposes new budget
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        budgets = AnnualBudget.objects.prefetch_related('envelopes').order_by('-year')
        return Response(AnnualBudgetSerializer(budgets, many=True).data)

    def post(self, request):
        role = getattr(getattr(request.user, 'role', None), 'name', '')
        if role not in ('FINANCE', 'NATIONAL_FINANCE_HEAD', 'NATIONAL_FINANCE_DEPUTY',
                        'BELT_FINANCE_OFFICER', 'BELT_FINANCE_DEPUTY',
                        'REGIONAL_FINANCE_OFFICER', 'REGIONAL_FINANCE_DEPUTY', 'SUPER_ADMIN'):
            return Response(
                {'detail': 'Only Finance can propose a budget.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = AnnualBudgetCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        budget, errors = BudgetService.propose(
            year        = serializer.validated_data['year'],
            envelopes   = serializer.validated_data['envelopes'],
            proposed_by = request.user,
        )
        if errors:
            return Response({'detail': errors[0]}, status=status.HTTP_400_BAD_REQUEST)

        return Response(AnnualBudgetSerializer(budget).data, status=status.HTTP_201_CREATED)


class AnnualBudgetDetailView(APIView):
    """
    GET /api/v1/procurement/budgets/<pk>/
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            budget = AnnualBudget.objects.prefetch_related('envelopes').get(pk=pk)
        except AnnualBudget.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(AnnualBudgetSerializer(budget).data)


class AnnualBudgetApproveView(APIView):
    """
    POST /api/v1/procurement/budgets/<pk>/approve/
    Owner (SUPER_ADMIN) approves the budget.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            budget = AnnualBudget.objects.get(pk=pk)
        except AnnualBudget.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        budget, errors = BudgetService.approve(budget, approved_by=request.user)
        if errors:
            return Response({'detail': errors[0]}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            'id'         : budget.pk,
            'status'     : budget.status,
            'approved_at': budget.approved_at.isoformat(),
            'message'    : f'Budget {budget.year} approved. All envelopes are now active.',
        })


class BudgetEnvelopeListView(APIView):
    """
    GET /api/v1/procurement/budgets/<pk>/envelopes/
    Returns all envelopes for a budget, grouped by category.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            budget = AnnualBudget.objects.get(pk=pk)
        except AnnualBudget.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        envelopes = budget.envelopes.all().order_by('category', 'period_type')

        # Group by category
        grouped = {}
        for env in envelopes:
            cat = env.category
            if cat not in grouped:
                grouped[cat] = {
                    'category'        : cat,
                    'category_display': env.get_category_display(),
                    'envelopes'       : [],
                }
            grouped[cat]['envelopes'].append(
                BudgetEnvelope.__dict__  # use serializer below
            )

        from apps.procurement.api.serializers_budget import BudgetEnvelopeSerializer
        result = []
        for cat, data in grouped.items():
            cat_envelopes = envelopes.filter(category=cat)
            result.append({
                'category'        : cat,
                'category_display': cat_envelopes.first().get_category_display(),
                'envelopes'       : BudgetEnvelopeSerializer(cat_envelopes, many=True).data,
            })

        return Response({'year': budget.year, 'status': budget.status, 'categories': result})


class VendorListView(APIView):
    """
    GET  /api/v1/procurement/vendors/  — list all vendors
    POST /api/v1/procurement/vendors/  — create vendor
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        vendors = Vendor.objects.prefetch_related('items__consumable').filter(is_active=True)
        return Response(VendorSerializer(vendors, many=True).data)

    def post(self, request):
        role = getattr(getattr(request.user, 'role', None), 'name', '')
        if role not in ('FINANCE', 'NATIONAL_FINANCE_HEAD', 'NATIONAL_FINANCE_DEPUTY',
                        'BELT_FINANCE_OFFICER', 'BELT_FINANCE_DEPUTY',
                        'REGIONAL_FINANCE_OFFICER', 'REGIONAL_FINANCE_DEPUTY', 'SUPER_ADMIN'):
            return Response(
                {'detail': 'Only Finance can manage vendors.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = VendorSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        vendor = serializer.save()
        return Response(VendorSerializer(vendor).data, status=status.HTTP_201_CREATED)


class VendorDetailView(APIView):
    """
    GET   /api/v1/procurement/vendors/<pk>/
    PATCH /api/v1/procurement/vendors/<pk>/
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            vendor = Vendor.objects.prefetch_related('items__consumable').get(pk=pk)
        except Vendor.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(VendorSerializer(vendor).data)

    def patch(self, request, pk):
        try:
            vendor = Vendor.objects.get(pk=pk)
        except Vendor.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = VendorSerializer(vendor, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        vendor = serializer.save()
        return Response(VendorSerializer(vendor).data)


class VendorItemCreateView(APIView):
    """
    POST /api/v1/procurement/vendors/<pk>/items/
    Add a consumable + price to a vendor pricelist.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            vendor = Vendor.objects.get(pk=pk)
        except Vendor.DoesNotExist:
            return Response({'detail': 'Vendor not found.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = VendorItemSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        item = serializer.save(vendor=vendor)
        return Response(VendorItemSerializer(item).data, status=status.HTTP_201_CREATED)


class ReceiptUploadView(APIView):
    """
    POST /api/v1/procurement/orders/<pk>/receipt/
    Operations uploads receipt after purchase.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        from apps.procurement.models import ReplenishmentOrder
        from django.utils import timezone

        try:
            order = ReplenishmentOrder.objects.get(pk=pk)
        except ReplenishmentOrder.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        if order.status != ReplenishmentOrder.Status.DELIVERED:
            return Response(
                {'detail': 'Receipt can only be uploaded after delivery.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        receipt = request.FILES.get('receipt')
        if not receipt:
            return Response(
                {'detail': 'No receipt file provided.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        disbursement_method    = request.data.get('disbursement_method', '')
        disbursement_reference = request.data.get('disbursement_reference', '')

        order.receipt                = receipt
        order.receipt_uploaded_at    = timezone.now()
        order.receipt_uploaded_by    = request.user
        order.disbursement_method    = disbursement_method
        order.disbursement_reference = disbursement_reference
        order.save(update_fields=[
            'receipt', 'receipt_uploaded_at', 'receipt_uploaded_by',
            'disbursement_method', 'disbursement_reference', 'updated_at',
        ])

        return Response({'detail': 'Receipt uploaded. Awaiting Finance verification.'})


class ReceiptVerifyView(APIView):
    """
    POST /api/v1/procurement/orders/<pk>/verify-receipt/
    Finance verifies receipt and closes the loop.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        from apps.procurement.models import ReplenishmentOrder
        from django.utils import timezone
        from decimal import Decimal

        role = getattr(getattr(request.user, 'role', None), 'name', '')
        if role not in ('FINANCE', 'NATIONAL_FINANCE_HEAD', 'NATIONAL_FINANCE_DEPUTY',
                        'BELT_FINANCE_OFFICER', 'BELT_FINANCE_DEPUTY',
                        'REGIONAL_FINANCE_OFFICER', 'REGIONAL_FINANCE_DEPUTY', 'SUPER_ADMIN'):
            return Response(
                {'detail': 'Only Finance can verify receipts.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            order = ReplenishmentOrder.objects.get(pk=pk)
        except ReplenishmentOrder.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        if not order.receipt:
            return Response(
                {'detail': 'No receipt uploaded yet.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        actual_amount = request.data.get('actual_amount')
        if not actual_amount:
            return Response(
                {'detail': 'actual_amount is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        actual_amount = Decimal(str(actual_amount))

        # Check variance against approved budget
        variance_flagged = False
        if order.approved_budget:
            variance_pct = abs(actual_amount - order.approved_budget) / order.approved_budget * 100
            variance_flagged = variance_pct > Decimal('5')

        order.receipt_verified          = True
        order.receipt_verified_by       = request.user
        order.receipt_verified_at       = timezone.now()
        order.receipt_variance_flagged  = variance_flagged
        order.status                    = ReplenishmentOrder.Status.CLOSED
        order.save(update_fields=[
            'receipt_verified', 'receipt_verified_by', 'receipt_verified_at',
            'receipt_variance_flagged', 'status', 'updated_at',
        ])

        if variance_flagged:
            import logging
            logging.getLogger(__name__).warning(
                'ReceiptVerifyView: variance flagged on order %s — approved GHS %s, actual GHS %s',
                order.order_number, order.approved_budget, actual_amount,
            )

        return Response({
            'detail'           : 'Receipt verified. Order closed.',
            'variance_flagged' : variance_flagged,
            'order_number'     : order.order_number,
            'status'           : order.status,
        })


class CurrentEnvelopeView(APIView):
    """
    GET /api/v1/procurement/envelopes/current/?category=STOCK
    Returns the active quarterly envelope for a category in the current year.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.utils import timezone
        category = request.query_params.get('category')
        if not category:
            return Response(
                {'detail': 'category query param is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        year     = timezone.localdate().year
        envelope = BudgetService.get_active_envelope(year=year, category=category)

        if not envelope:
            return Response(
                {'detail': f'No active {category} envelope for {year}.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        from apps.procurement.api.serializers_budget import BudgetEnvelopeSerializer
        return Response(BudgetEnvelopeSerializer(envelope).data)