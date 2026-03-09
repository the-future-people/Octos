from rest_framework import generics, filters
from rest_framework.permissions import IsAuthenticated
from apps.organization.models import Belt, Region, Branch
from .serializers import BeltSerializer, RegionSerializer, BranchSerializer, BranchListSerializer


class BeltListView(generics.ListAPIView):
    queryset = Belt.objects.all()
    serializer_class = BeltSerializer
    permission_classes = [IsAuthenticated]


class RegionListView(generics.ListAPIView):
    queryset = Region.objects.select_related('belt').all()
    serializer_class = RegionSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ['belt']

    def get_queryset(self):
        qs = super().get_queryset()
        belt_id = self.request.query_params.get('belt')
        if belt_id:
            qs = qs.filter(belt_id=belt_id)
        return qs


class BranchListView(generics.ListAPIView):
    queryset = Branch.objects.select_related('region', 'region__belt').all()
    serializer_class = BranchSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ['name', 'code']

    def get_queryset(self):
        qs = super().get_queryset()
        region_id = self.request.query_params.get('region')
        is_active = self.request.query_params.get('is_active')
        if region_id:
            qs = qs.filter(region_id=region_id)
        if is_active is not None:
            qs = qs.filter(is_active=is_active.lower() == 'true')
        return qs


class BranchDetailView(generics.RetrieveAPIView):
    queryset = Branch.objects.select_related('region', 'region__belt').all()
    serializer_class = BranchSerializer
    permission_classes = [IsAuthenticated]


class BranchDropdownView(generics.ListAPIView):
    """Lightweight endpoint for dropdowns and selects."""
    queryset = Branch.objects.filter(is_active=True).all()
    serializer_class = BranchListSerializer
    permission_classes = [IsAuthenticated]