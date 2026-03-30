from rest_framework import generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from apps.inventory.models import (
    ConsumableItem, BranchStock, StockMovement, WasteIncident,
    BranchEquipment, MaintenanceLog,
)
from .serializers import (
    BranchStockSerializer, StockMovementSerializer,
    WasteIncidentSerializer, ReceiveStockSerializer,
    WasteIncidentCreateSerializer,
    BranchEquipmentSerializer, BranchEquipmentCreateSerializer,
    MaintenanceLogSerializer, MaintenanceLogCreateSerializer,
)

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
        ).exclude(
            consumable__category__name = 'Machinery',
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

class BranchEquipmentListView(APIView):
    """GET /api/v1/inventory/equipment/ — list all equipment for branch"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        branch = getattr(request.user, 'branch', None)
        if not branch:
            return Response([], status=status.HTTP_200_OK)
        equipment = BranchEquipment.objects.filter(
            branch    = branch,
            is_active = True,
        ).prefetch_related('maintenance_logs').order_by('name')
        return Response(BranchEquipmentSerializer(equipment, many=True).data)

    def post(self, request):
        branch = getattr(request.user, 'branch', None)
        if not branch:
            return Response({'detail': 'No branch assigned.'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = BranchEquipmentCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        d = serializer.validated_data
        equipment = BranchEquipment.objects.create(
            branch          = branch,
            name            = d['name'],
            quantity        = d.get('quantity', 1),
            condition       = d.get('condition', 'GOOD'),
            serial_number   = d.get('serial_number', ''),
            model_number    = d.get('model_number', ''),
            manufacturer    = d.get('manufacturer', ''),
            purchase_date   = d.get('purchase_date'),
            purchase_price  = d.get('purchase_price'),
            warranty_expiry = d.get('warranty_expiry'),
            location        = d.get('location', ''),
            notes           = d.get('notes', ''),
        )
        return Response(
            BranchEquipmentSerializer(equipment).data,
            status=status.HTTP_201_CREATED,
        )


class BranchEquipmentDetailView(APIView):
    """GET/PATCH /api/v1/inventory/equipment/<id>/"""
    permission_classes = [IsAuthenticated]

    def _get_equipment(self, pk, branch):
        try:
            return BranchEquipment.objects.prefetch_related(
                'maintenance_logs'
            ).get(pk=pk, branch=branch)
        except BranchEquipment.DoesNotExist:
            return None

    def get(self, request, pk):
        branch = getattr(request.user, 'branch', None)
        equipment = self._get_equipment(pk, branch)
        if not equipment:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(BranchEquipmentSerializer(equipment).data)

    def patch(self, request, pk):
        branch = getattr(request.user, 'branch', None)
        equipment = self._get_equipment(pk, branch)
        if not equipment:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        allowed = ['condition', 'quantity', 'location', 'notes',
                   'serial_number', 'model_number', 'manufacturer',
                   'purchase_date', 'purchase_price', 'warranty_expiry',
                   'next_service_due', 'is_active']
        for field in allowed:
            if field in request.data:
                setattr(equipment, field, request.data[field])
        equipment.save()
        return Response(BranchEquipmentSerializer(equipment).data)


class MaintenanceLogListView(APIView):
    """
    GET  /api/v1/inventory/equipment/<id>/maintenance/ — list logs
    POST /api/v1/inventory/equipment/<id>/maintenance/ — add log
    """
    permission_classes = [IsAuthenticated]

    def _get_equipment(self, pk, branch):
        try:
            return BranchEquipment.objects.get(pk=pk, branch=branch)
        except BranchEquipment.DoesNotExist:
            return None

    def get(self, request, pk):
        branch = getattr(request.user, 'branch', None)
        equipment = self._get_equipment(pk, branch)
        if not equipment:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        logs = equipment.maintenance_logs.select_related('logged_by').all()
        return Response(MaintenanceLogSerializer(logs, many=True).data)

    def post(self, request, pk):
        branch = getattr(request.user, 'branch', None)
        equipment = self._get_equipment(pk, branch)
        if not equipment:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = MaintenanceLogCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        d = serializer.validated_data
        log = MaintenanceLog.objects.create(
            equipment       = equipment,
            log_type        = d['log_type'],
            service_date    = d['service_date'],
            description     = d['description'],
            performed_by    = d['performed_by'],
            cost            = d.get('cost'),
            parts_replaced  = d.get('parts_replaced', ''),
            next_due        = d.get('next_due'),
            condition_after = d['condition_after'],
            logged_by       = request.user,
            notes           = d.get('notes', ''),
        )
        return Response(
            MaintenanceLogSerializer(log).data,
            status=status.HTTP_201_CREATED,
        )


class EquipmentQRView(APIView):
    """
    GET /api/v1/inventory/equipment/<id>/qr/
    Returns a QR code PNG for the equipment asset tag.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        branch = getattr(request.user, 'branch', None)
        try:
            equipment = BranchEquipment.objects.get(pk=pk, branch=branch)
        except BranchEquipment.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        try:
            import qrcode
            import io
            from django.http import HttpResponse

            # QR encodes the asset code + name for scanning
            qr_data = (
                f"FARHAT PRINTING PRESS\n"
                f"Asset: {equipment.asset_code}\n"
                f"Name: {equipment.name}\n"
                f"Branch: {equipment.branch.name}"
            )

            qr = qrcode.QRCode(
                version           = 1,
                error_correction  = qrcode.constants.ERROR_CORRECT_H,
                box_size          = 10,
                border            = 4,
            )
            qr.add_data(qr_data)
            qr.make(fit=True)
            img = qr.make_image(fill_color='black', back_color='white')

            buf = io.BytesIO()
            img.save(buf, format='PNG')
            buf.seek(0)

            response = HttpResponse(buf.read(), content_type='image/png')
            response['Content-Disposition'] = (
                f'attachment; filename="{equipment.asset_code}.png"'
            )
            return response

        except ImportError:
            return Response(
                {
                    'detail': 'QR generation not available — install qrcode library.',
                    'asset_code': equipment.asset_code,
                    'qr_data': qr_data,
                },
                status=status.HTTP_200_OK,
            )