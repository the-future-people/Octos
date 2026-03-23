from rest_framework import generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status

from apps.inventory.models import (
    ConsumableItem, BranchStock, StockMovement, WasteIncident,
)
from .serializers import (
    BranchStockSerializer, StockMovementSerializer,
    WasteIncidentSerializer, ReceiveStockSerializer,
    WasteIncidentCreateSerializer,
)


class BranchStockListView(generics.ListAPIView):
    """GET /api/v1/inventory/stock/ — current stock levels for user's branch"""
    serializer_class   = BranchStockSerializer
    permission_classes = [IsAuthenticated]
    pagination_class   = None

    def get_queryset(self):
        branch = getattr(self.request.user, 'branch', None)
        if not branch:
            return BranchStock.objects.none()
        return BranchStock.objects.filter(
            branch = branch,
        ).select_related(
            'consumable', 'consumable__category'
        ).order_by('consumable__category__name', 'consumable__paper_size', 'consumable__name')


class StockMovementListView(generics.ListAPIView):
    """GET /api/v1/inventory/movements/ — movement ledger for user's branch"""
    serializer_class   = StockMovementSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        branch = getattr(self.request.user, 'branch', None)
        if not branch:
            return StockMovement.objects.none()
        qs = StockMovement.objects.filter(
            branch = branch,
        ).select_related('consumable', 'recorded_by', 'reference_job').order_by('-created_at')

        # Optional filter by consumable
        consumable_id = self.request.query_params.get('consumable')
        if consumable_id:
            qs = qs.filter(consumable_id=consumable_id)

        # Optional filter by type
        movement_type = self.request.query_params.get('type')
        if movement_type:
            qs = qs.filter(movement_type=movement_type)

        return qs


class WasteIncidentListView(generics.ListAPIView):
    """GET /api/v1/inventory/waste/ — waste incidents for user's branch"""
    serializer_class   = WasteIncidentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        branch = getattr(self.request.user, 'branch', None)
        if not branch:
            return WasteIncident.objects.none()
        return WasteIncident.objects.filter(
            branch = branch,
        ).select_related(
            'consumable', 'reported_by', 'job'
        ).order_by('-created_at')


class ReceiveStockView(APIView):
    """POST /api/v1/inventory/stock/receive/ — BM receives new stock"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ReceiveStockSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        branch = getattr(request.user, 'branch', None)
        if not branch:
            return Response({'detail': 'No branch assigned.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            consumable = ConsumableItem.objects.get(
                pk        = serializer.validated_data['consumable_id'],
                is_active = True,
            )
        except ConsumableItem.DoesNotExist:
            return Response({'detail': 'Consumable not found.'}, status=status.HTTP_404_NOT_FOUND)

        from apps.inventory.inventory_engine import InventoryEngine
        movement = InventoryEngine(branch).receive_stock(
            consumable = consumable,
            quantity   = serializer.validated_data['quantity'],
            actor      = request.user,
            notes      = serializer.validated_data.get('notes', ''),
        )

        return Response(
            StockMovementSerializer(movement).data,
            status=status.HTTP_201_CREATED,
        )


class WasteIncidentCreateView(APIView):
    """POST /api/v1/inventory/waste/ — attendant reports a waste incident"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = WasteIncidentCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        branch = getattr(request.user, 'branch', None)
        if not branch:
            return Response({'detail': 'No branch assigned.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            consumable = ConsumableItem.objects.get(
                pk        = serializer.validated_data['consumable_id'],
                is_active = True,
            )
        except ConsumableItem.DoesNotExist:
            return Response({'detail': 'Consumable not found.'}, status=status.HTTP_404_NOT_FOUND)

        job = None
        job_id = serializer.validated_data.get('job_id')
        if job_id:
            from apps.jobs.models import Job
            try:
                job = Job.objects.get(pk=job_id, branch=branch)
            except Job.DoesNotExist:
                return Response({'detail': 'Job not found.'}, status=status.HTTP_404_NOT_FOUND)

        from apps.inventory.inventory_engine import InventoryEngine
        incident = InventoryEngine(branch).record_waste(
            consumable = consumable,
            quantity   = serializer.validated_data['quantity'],
            reason     = serializer.validated_data['reason'],
            actor      = request.user,
            job        = job,
            notes      = serializer.validated_data.get('notes', ''),
        )

        return Response(
            WasteIncidentSerializer(incident).data,
            status=status.HTTP_201_CREATED,
        )