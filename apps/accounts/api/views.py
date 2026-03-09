from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from apps.accounts.models import CustomUser, Role, Permission
from .serializers import (
    UserSerializer, UserCreateSerializer, ChangePasswordSerializer,
    RoleSerializer, RoleListSerializer, PermissionSerializer
)


class MeView(APIView):
    """Returns the currently authenticated user's profile."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            serializer.save()
            return Response({'detail': 'Password updated successfully.'})
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UserListView(generics.ListAPIView):
    queryset = CustomUser.objects.select_related('role', 'branch').all()
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        branch_id = self.request.query_params.get('branch')
        role_id = self.request.query_params.get('role')
        is_active = self.request.query_params.get('is_active')
        if branch_id:
            qs = qs.filter(branch_id=branch_id)
        if role_id:
            qs = qs.filter(role_id=role_id)
        if is_active is not None:
            qs = qs.filter(is_active=is_active.lower() == 'true')
        return qs


class UserDetailView(generics.RetrieveUpdateAPIView):
    queryset = CustomUser.objects.select_related('role', 'branch').all()
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]


class UserCreateView(generics.CreateAPIView):
    serializer_class = UserCreateSerializer
    permission_classes = [IsAuthenticated]


class RoleListView(generics.ListAPIView):
    queryset = Role.objects.prefetch_related('permissions').all()
    serializer_class = RoleSerializer
    permission_classes = [IsAuthenticated]


class RoleDropdownView(generics.ListAPIView):
    queryset = Role.objects.all()
    serializer_class = RoleListSerializer
    permission_classes = [IsAuthenticated]


class PermissionListView(generics.ListAPIView):
    queryset = Permission.objects.all()
    serializer_class = PermissionSerializer
    permission_classes = [IsAuthenticated]