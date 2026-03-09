from rest_framework import serializers
from apps.organization.models import Belt, Region, Branch


class BeltSerializer(serializers.ModelSerializer):
    class Meta:
        model = Belt
        fields = ['id', 'name', 'code', 'created_at']


class RegionSerializer(serializers.ModelSerializer):
    belt_name = serializers.CharField(source='belt.name', read_only=True)

    class Meta:
        model = Region
        fields = ['id', 'name', 'code', 'belt', 'belt_name', 'created_at']


class BranchSerializer(serializers.ModelSerializer):
    region_name = serializers.CharField(source='region.name', read_only=True)
    belt_name = serializers.CharField(source='region.belt.name', read_only=True)
    load_percentage = serializers.FloatField(read_only=True)
    is_available = serializers.BooleanField(read_only=True)

    class Meta:
        model = Branch
        fields = [
            'id', 'name', 'code', 'region', 'region_name', 'belt_name',
            'is_headquarters', 'is_regional_hq', 'address', 'phone',
            'whatsapp_number', 'email', 'capacity_score', 'current_load',
            'load_percentage', 'is_available', 'is_active', 'created_at'
        ]


class BranchListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for lists and dropdowns."""
    load_percentage = serializers.FloatField(read_only=True)
    is_available = serializers.BooleanField(read_only=True)

    class Meta:
        model = Branch
        fields = ['id', 'name', 'code', 'is_headquarters', 'load_percentage', 'is_available']