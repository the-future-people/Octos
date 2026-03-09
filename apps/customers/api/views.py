from rest_framework import generics, filters, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from apps.customers.models import CustomerProfile
from .serializers import CustomerSerializer, CustomerListSerializer, CustomerCreateSerializer


class CustomerListView(generics.ListAPIView):
    queryset = CustomerProfile.objects.select_related('preferred_branch').all()
    serializer_class = CustomerListSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ['phone', 'first_name', 'last_name', 'email']

    def get_queryset(self):
        qs = super().get_queryset()
        tier = self.request.query_params.get('tier')
        is_priority = self.request.query_params.get('is_priority')
        if tier:
            qs = qs.filter(tier=tier)
        if is_priority is not None:
            qs = qs.filter(is_priority=is_priority.lower() == 'true')
        return qs


class CustomerDetailView(generics.RetrieveUpdateAPIView):
    queryset = CustomerProfile.objects.select_related('preferred_branch').all()
    serializer_class = CustomerSerializer
    permission_classes = [IsAuthenticated]


class CustomerCreateView(generics.CreateAPIView):
    serializer_class = CustomerCreateSerializer
    permission_classes = [IsAuthenticated]


class CustomerLookupView(APIView):
    """
    Look up a customer by phone number.
    Used by attendants when a customer walks in or calls.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        phone = request.query_params.get('phone')
        if not phone:
            return Response(
                {'detail': 'Phone number is required.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        try:
            customer = CustomerProfile.objects.get(phone=phone)
            serializer = CustomerSerializer(customer)
            return Response(serializer.data)
        except CustomerProfile.DoesNotExist:
            return Response(
                {'detail': 'Customer not found.'},
                status=status.HTTP_404_NOT_FOUND
            )