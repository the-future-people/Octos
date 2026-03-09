from rest_framework import serializers
from apps.customers.models import CustomerProfile


class CustomerSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    preferred_branch_name = serializers.CharField(
        source='preferred_branch.name', read_only=True
    )

    class Meta:
        model = CustomerProfile
        fields = [
            'id', 'first_name', 'last_name', 'full_name',
            'phone', 'email', 'visit_count', 'tier',
            'preferred_branch', 'preferred_branch_name',
            'is_priority', 'notes', 'created_at'
        ]


class CustomerListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for lists and dropdowns."""
    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = CustomerProfile
        fields = ['id', 'full_name', 'phone', 'tier', 'is_priority']


class CustomerCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerProfile
        fields = [
            'first_name', 'last_name', 'phone', 'email',
            'preferred_branch', 'notes'
        ]