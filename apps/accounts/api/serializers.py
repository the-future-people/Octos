from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from apps.accounts.models import CustomUser, Role, Permission
from apps.organization.models import Branch, Region


class PermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permission
        fields = ['id', 'name', 'codename', 'description']


class RoleSerializer(serializers.ModelSerializer):
    permissions = PermissionSerializer(many=True, read_only=True)

    class Meta:
        model = Role
        fields = ['id', 'name', 'codename', 'description', 'permissions']


class RoleListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for dropdowns."""
    class Meta:
        model  = Role
        fields = ['id', 'name', 'display_name', 'is_constrained', 'scope']


class BranchMinimalSerializer(serializers.ModelSerializer):
    region_name = serializers.CharField(source='region.name', read_only=True)
    belt_name   = serializers.CharField(source='region.belt.name', read_only=True)

    class Meta:
        model  = Branch
        fields = ['id', 'name', 'code', 'region_name', 'belt_name']


class RegionMinimalSerializer(serializers.ModelSerializer):
    belt_name = serializers.CharField(source='belt.name', read_only=True)

    class Meta:
        model  = Region
        fields = ['id', 'name', 'code', 'belt_name']


class UserSerializer(serializers.ModelSerializer):
    role_detail   = RoleListSerializer(source='role',   read_only=True)
    branch_detail = BranchMinimalSerializer(source='branch', read_only=True)
    region_detail = RegionMinimalSerializer(source='region', read_only=True)
    full_name     = serializers.SerializerMethodField()
    role_name     = serializers.SerializerMethodField()

    class Meta:
        model  = CustomUser
        fields = [
            'id', 'email', 'first_name', 'last_name', 'full_name',
            'role', 'role_name', 'role_detail',
            'branch', 'branch_detail',
            'region', 'region_detail',
            'phone', 'employee_id', 'is_active', 'created_at',
            'download_pin_set',
        ]

    def get_role_name(self, obj):
        return obj.role.name if obj.role else None

    def get_full_name(self, obj):
        return obj.full_name or obj.email


class UserCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])

    class Meta:
        model = CustomUser
        fields = [
            'email', 'first_name', 'last_name', 'password',
            'role', 'branch', 'region', 'phone', 'employee_id',
        ]

    def create(self, validated_data):
        password = validated_data.pop('password')
        user = CustomUser(**validated_data)
        user.set_password(password)
        user.save()
        return user


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, validators=[validate_password])

    def validate_old_password(self, value):
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError('Old password is incorrect.')
        return value

    def save(self):
        user = self.context['request'].user
        user.set_password(self.validated_data['new_password'])
        user.save()
        return user