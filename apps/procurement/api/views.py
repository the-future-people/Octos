"""
Procurement API Views
=====================
Views are intentionally thin.
  - Authenticate and authorise the request
  - Validate input via serializer
  - Delegate to service (writes) or selector (reads)
  - Return serialized response

No business logic lives here.
"""
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from apps.procurement.api.serializers import (
    ReplenishmentOrderListSerializer,
    ReplenishmentOrderDetailSerializer,
    GenerateOrderSerializer,
    SubmitToFinanceSerializer,
    ApproveOrderSerializer,
    RejectOrderSerializer,
    DispatchOrderSerializer,
    RecordDeliverySerializer,
    AcceptDeliverySerializer,
    CancelOrderSerializer,
)
from apps.procurement import selectors, services


def _get_order_or_404(order_id: int):
    from apps.procurement.models import ReplenishmentOrder
    try:
        return selectors.get_order_by_id(order_id)
    except ReplenishmentOrder.DoesNotExist:
        return None


class ReplenishmentOrderListView(APIView):
    """
    GET  /api/v1/procurement/orders/
    Returns orders scoped to the requesting user's role.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user      = request.user
        role_name = getattr(getattr(user, 'role', None), 'name', '')

        if role_name in ('OPERATIONS_MANAGER', 'SUPER_ADMIN'):
            orders = selectors.get_orders_for_operations_manager()

        elif role_name == 'FINANCE':
            orders = selectors.get_orders_pending_finance_approval()

        elif role_name == 'REGIONAL_MANAGER' and user.region:
            orders = selectors.get_orders_for_rm(user.region)

        elif role_name == 'BRANCH_MANAGER' and user.branch:
            orders = selectors.get_orders_for_branch(user.branch)

        else:
            return Response(
                {'detail': 'You do not have permission to view replenishment orders.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = ReplenishmentOrderListSerializer(orders, many=True)
        return Response(serializer.data)


class ReplenishmentOrderDetailView(APIView):
    """
    GET /api/v1/procurement/orders/<pk>/
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        order = _get_order_or_404(pk)
        if order is None:
            return Response({'detail': 'Order not found.'}, status=status.HTTP_404_NOT_FOUND)

        if not _can_view_order(request.user, order):
            return Response({'detail': 'Access denied.'}, status=status.HTTP_403_FORBIDDEN)

        from apps.procurement.api.serializers import ReplenishmentLineItemDetailSerializer
        data = ReplenishmentOrderDetailSerializer(order).data
        data['line_items'] = ReplenishmentLineItemDetailSerializer(
            order.line_items.select_related(
                'consumable', 'consumable__category', 'consumable__delivery_unit'
            ).order_by('consumable__category__name', 'consumable__name'),
            many=True,
        ).data
        return Response(data)


class GenerateOrderView(APIView):
    """
    POST /api/v1/procurement/orders/generate/
    Generate a ReplenishmentOrder from a locked WeeklyReport.
    Operations Manager only.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        _require_role(request.user, {'OPERATIONS_MANAGER', 'SUPER_ADMIN'})

        serializer = GenerateOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        from apps.finance.models import WeeklyReport
        try:
            weekly_report = WeeklyReport.objects.select_related('branch').get(
                pk=serializer.validated_data['weekly_report_id']
            )
        except WeeklyReport.DoesNotExist:
            return Response(
                {'detail': 'Weekly report not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            order = services.generate_order_from_weekly_report(
                weekly_report = weekly_report,
                actor         = request.user,
            )
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            ReplenishmentOrderDetailSerializer(
                selectors.get_order_by_id(order.pk)
            ).data,
            status=status.HTTP_201_CREATED,
        )


class SubmitToFinanceView(APIView):
    """
    POST /api/v1/procurement/orders/<pk>/submit-finance/
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        _require_role(request.user, {'OPERATIONS_MANAGER', 'SUPER_ADMIN'})

        order = _get_order_or_404(pk)
        if order is None:
            return Response({'detail': 'Order not found.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = SubmitToFinanceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            order = services.submit_to_finance(order=order, actor=request.user)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(ReplenishmentOrderListSerializer(order).data)


class ApproveOrderView(APIView):
    """
    POST /api/v1/procurement/orders/<pk>/approve/
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        _require_role(request.user, {'FINANCE', 'SUPER_ADMIN'})

        order = _get_order_or_404(pk)
        if order is None:
            return Response({'detail': 'Order not found.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = ApproveOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        try:
            order = services.approve_order(
                order            = order,
                actor            = request.user,
                approved_budget  = d['approved_budget'],
                finance_notes    = d['finance_notes'],
                line_adjustments = d.get('line_adjustments'),
            )
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(ReplenishmentOrderListSerializer(order).data)


class RejectOrderView(APIView):
    """
    POST /api/v1/procurement/orders/<pk>/reject/
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        _require_role(request.user, {'FINANCE', 'SUPER_ADMIN'})

        order = _get_order_or_404(pk)
        if order is None:
            return Response({'detail': 'Order not found.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = RejectOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            order = services.reject_order(
                order         = order,
                actor         = request.user,
                finance_notes = serializer.validated_data['finance_notes'],
            )
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(ReplenishmentOrderListSerializer(order).data)


class DispatchOrderView(APIView):
    """
    POST /api/v1/procurement/orders/<pk>/dispatch/
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        _require_role(request.user, {'OPERATIONS_MANAGER', 'SUPER_ADMIN'})

        order = _get_order_or_404(pk)
        if order is None:
            return Response({'detail': 'Order not found.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = DispatchOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            order = services.dispatch_order(
                order     = order,
                actor     = request.user,
                ops_notes = serializer.validated_data['ops_notes'],
            )
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(ReplenishmentOrderListSerializer(order).data)


class RecordDeliveryView(APIView):
    """
    POST /api/v1/procurement/orders/<pk>/deliver/
    Operations records actual quantities delivered.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        _require_role(request.user, {'OPERATIONS_MANAGER', 'SUPER_ADMIN'})

        order = _get_order_or_404(pk)
        if order is None:
            return Response({'detail': 'Order not found.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = RecordDeliverySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            order = services.record_delivery(
                order                = order,
                actor                = request.user,
                delivered_quantities = serializer.validated_data['delivered_quantities'],
            )
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            ReplenishmentOrderDetailSerializer(
                selectors.get_order_by_id(order.pk)
            ).data
        )


class AcceptDeliveryView(APIView):
    """
    POST /api/v1/procurement/orders/<pk>/accept/
    BM accepts delivery — stocks are populated automatically.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        _require_role(request.user, {'BRANCH_MANAGER', 'SUPER_ADMIN'})

        order = _get_order_or_404(pk)
        if order is None:
            return Response({'detail': 'Order not found.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = AcceptDeliverySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        try:
            order = services.accept_delivery(
                order               = order,
                actor               = request.user,
                accepted_quantities = d['accepted_quantities'],
                bm_notes            = d['bm_notes'],
                returns             = d.get('returns'),
            )
        except (ValueError, PermissionError) as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            ReplenishmentOrderDetailSerializer(
                selectors.get_order_by_id(order.pk)
            ).data
        )


class CancelOrderView(APIView):
    """
    POST /api/v1/procurement/orders/<pk>/cancel/
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        _require_role(request.user, {'OPERATIONS_MANAGER', 'SUPER_ADMIN'})

        order = _get_order_or_404(pk)
        if order is None:
            return Response({'detail': 'Order not found.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = CancelOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            order = services.cancel_order(
                order  = order,
                actor  = request.user,
                reason = serializer.validated_data['reason'],
            )
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(ReplenishmentOrderListSerializer(order).data)


class PendingDeliveryForBranchView(APIView):
    """
    GET /api/v1/procurement/pending-delivery/
    BM dashboard widget — returns the in-transit delivery awaiting acceptance.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        _require_role(request.user, {'BRANCH_MANAGER', 'SUPER_ADMIN'})

        branch = request.user.branch
        if branch is None:
            return Response(
                {'detail': 'No branch assigned.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        order = selectors.get_pending_delivery_for_branch(branch)
        if order is None:
            return Response(None)

        return Response(
            ReplenishmentOrderDetailSerializer(order).data
        )


# ── Authorisation helpers ─────────────────────────────────────────────────────

def _require_role(user, allowed_roles: set) -> None:
    role_name = getattr(getattr(user, 'role', None), 'name', '')
    if role_name not in allowed_roles:
        from rest_framework.exceptions import PermissionDenied
        raise PermissionDenied(
            f"This action requires one of: {', '.join(sorted(allowed_roles))}."
        )


def _can_view_order(user, order) -> bool:
    role_name = getattr(getattr(user, 'role', None), 'name', '')
    if role_name in ('OPERATIONS_MANAGER', 'FINANCE', 'SUPER_ADMIN'):
        return True
    if role_name == 'REGIONAL_MANAGER':
        return order.branch.region_id == getattr(user, 'region_id', None)
    if role_name == 'BRANCH_MANAGER':
        return order.branch_id == getattr(user, 'branch_id', None)
    return False


class BranchDeliveryStatusView(APIView):
    """
    GET /api/v1/procurement/branches/
    Returns all branches with their delivery health status.
    Operations Manager only.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        _require_role(request.user, {'OPERATIONS_MANAGER', 'SUPER_ADMIN'})
        from apps.procurement.api.serializers import BranchDeliveryStatusSerializer
        data = selectors.get_all_branches_with_delivery_status()
        return Response(BranchDeliveryStatusSerializer(data, many=True).data)


class PrepareDeliverablesView(APIView):
    """
    POST /api/v1/procurement/branches/<branch_id>/prepare/
    Auto-generate a replenishment order from the branch's latest locked EOW.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, branch_id):
        _require_role(request.user, {'OPERATIONS_MANAGER', 'SUPER_ADMIN'})

        from apps.organization.models import Branch
        try:
            branch = Branch.objects.get(pk=branch_id, is_active=True)
        except Branch.DoesNotExist:
            return Response({'detail': 'Branch not found.'}, status=status.HTTP_404_NOT_FOUND)

        try:
            order = services.prepare_deliverables(branch=branch, actor=request.user)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            ReplenishmentOrderDetailSerializer(
                selectors.get_order_by_id(order.pk)
            ).data,
            status=status.HTTP_201_CREATED,
        )


class ActiveOrderForBranchView(APIView):
    """
    GET /api/v1/procurement/branches/<branch_id>/active-order/
    Returns the active order for a branch (if any).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, branch_id):
        _require_role(request.user, {'OPERATIONS_MANAGER', 'SUPER_ADMIN'})

        from apps.organization.models import Branch
        try:
            branch = Branch.objects.get(pk=branch_id)
        except Branch.DoesNotExist:
            return Response({'detail': 'Branch not found.'}, status=status.HTTP_404_NOT_FOUND)

        order = selectors.get_active_order_for_branch(branch)
        if order is None:
            return Response(None)

        from apps.procurement.api.serializers import ReplenishmentLineItemDetailSerializer
        data = ReplenishmentOrderDetailSerializer(order).data
        # Override line_items with pack-aware serializer
        data['line_items'] = ReplenishmentLineItemDetailSerializer(
            order.line_items.select_related(
                'consumable', 'consumable__category', 'consumable__delivery_unit'
            ).order_by('consumable__category__name', 'consumable__name'),
            many=True,
        ).data
        return Response(data)


class ConfirmOrderView(APIView):
    """
    POST /api/v1/procurement/orders/<pk>/confirm/
    Ops confirms a DRAFT order — marks it CONFIRMED, ready for dispatch.
    No Finance involvement for weekly distribution.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        _require_role(request.user, {'OPERATIONS_MANAGER', 'SUPER_ADMIN'})

        order = _get_order_or_404(pk)
        if order is None:
            return Response({'detail': 'Order not found.'}, status=status.HTTP_404_NOT_FOUND)

        if order.status != 'DRAFT':
            return Response(
                {'detail': f"Cannot confirm order in status '{order.status}'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        order.status = 'CONFIRMED'
        order.save(update_fields=['status', 'updated_at'])

        return Response(ReplenishmentOrderListSerializer(order).data)