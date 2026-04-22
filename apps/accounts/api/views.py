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
    pagination_class = None


class PermissionListView(generics.ListAPIView):
    queryset = Permission.objects.all()
    serializer_class = PermissionSerializer
    permission_classes = [IsAuthenticated]

class SetDownloadPinView(APIView):
    """
    POST /api/v1/accounts/pin/set/
    Sets or updates the BM's 4-digit download PIN.
    Body: { "pin": "1234", "confirm_pin": "1234" }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        pin         = str(request.data.get('pin', '')).strip()
        confirm_pin = str(request.data.get('confirm_pin', '')).strip()

        if not pin or not confirm_pin:
            return Response(
                {'detail': 'Both pin and confirm_pin are required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if len(pin) != 4 or not pin.isdigit():
            return Response(
                {'detail': 'PIN must be exactly 4 digits.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if pin != confirm_pin:
            return Response(
                {'detail': 'PINs do not match.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        request.user.set_download_pin(pin)
        return Response({'detail': 'Download PIN set successfully.'})


class VerifyDownloadPinView(APIView):
    """
    POST /api/v1/accounts/pin/verify/
    Verifies the PIN and logs the sheet download.
    Body: { "pin": "1234", "sheet_id": 13 }
    Returns: { "valid": true, "token": "<one-time-token>" }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from apps.finance.models import DailySalesSheet, SheetDownloadLog

        pin      = str(request.data.get('pin', '')).strip()
        sheet_id = request.data.get('sheet_id')

        if not pin or not sheet_id:
            return Response(
                {'detail': 'pin and sheet_id are required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check PIN is set
        if not request.user.download_pin_set:
            return Response(
                {'detail': 'No PIN set.', 'requires_setup': True},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Verify PIN
        if not request.user.verify_download_pin(pin):
            return Response(
                {'detail': 'Incorrect PIN. Please try again.', 'valid': False},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Verify sheet exists and belongs to user's branch
        try:
            sheet = DailySalesSheet.objects.get(
                pk=sheet_id,
                branch=request.user.branch,
            )
        except DailySalesSheet.DoesNotExist:
            return Response(
                {'detail': 'Sheet not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Log the download
        ip = (
            request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip()
            or request.META.get('REMOTE_ADDR')
        )
        SheetDownloadLog.objects.create(
            sheet         = sheet,
            downloaded_by = request.user,
            ip_address    = ip or None,
        )

        return Response({'valid': True, 'sheet_id': sheet.id})

from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework.response import Response

class AuditedTokenObtainPairView(TokenObtainPairView):
    """
    Extends SimpleJWT token view to write AuditEvent on login.
    Replaces TokenObtainPairView in config/urls.py.
    """
    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)

        if response.status_code == 200:
            # Login succeeded — write audit event
            try:
                from apps.accounts.models import CustomUser
                from apps.analytics.signals.handlers import _write_event, _get_ip

                email = request.data.get('email', '') or request.data.get('username', '')
                user  = CustomUser.objects.filter(email=email).first()

                if user:
                    _write_event(
                        event_type  = 'LOGIN_SUCCESS',
                        severity    = 'INFO',
                        user        = user,
                        branch      = getattr(user, 'branch', None),
                        entity_type = 'CustomUser',
                        entity_id   = user.pk,
                        metadata    = {
                            'email'      : user.email,
                            'role'       : getattr(getattr(user, 'role', None), 'name', None),
                            'branch_code': getattr(getattr(user, 'branch', None), 'code', None),
                            'ip'         : _get_ip(request),
                            'user_agent' : request.META.get('HTTP_USER_AGENT', '')[:200],
                        },
                    )
            except Exception:
                pass  # Never break login over audit failure
        else:
            # Login failed
            try:
                from apps.analytics.signals.handlers import _write_event, _get_ip
                _write_event(
                    event_type = 'LOGIN_FAILED',
                    severity   = 'MEDIUM',
                    metadata   = {
                        'email'     : request.data.get('email', ''),
                        'ip'        : _get_ip(request),
                        'user_agent': request.META.get('HTTP_USER_AGENT', '')[:200],
                    },
                )
            except Exception:
                pass

        return response

class PendingActivationMeView(APIView):
    """
    GET /api/v1/accounts/pending-activation/me/
    Returns the current user's own PendingActivation (for shadow employees).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.accounts.models import PendingActivation
        try:
            pa = PendingActivation.objects.select_related(
                'role', 'branch', 'region'
            ).get(user=request.user)
        except PendingActivation.DoesNotExist:
            return Response({'detail': 'No pending activation found.'}, status=404)

        return Response({
            'id'              : pa.id,
            'start_date'      : str(pa.start_date),
            'days_until_start': pa.days_until_start,
            'role'            : pa.role.display_name,
            'designation'     : pa.designation,
            'status'          : pa.status,
            'shadow_days'     : pa.shadow_days,
        })


class PendingActivationDisplacingMeView(APIView):
    """
    GET /api/v1/accounts/pending-activation/displacing-me/
    Returns activation details for the incoming employee who will
    replace the current user (for outgoing BM countdown banner).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.accounts.models import PendingActivation
        pa = PendingActivation.objects.select_related(
            'user', 'role', 'branch',
        ).filter(
            conflict_user=request.user,
            status__in=[PendingActivation.PENDING, PendingActivation.SHADOW],
        ).order_by('start_date').first()

        if not pa:
            return Response({'detail': 'No incoming replacement found.'}, status=404)

        return Response({
            'id'              : pa.id,
            'start_date'      : str(pa.start_date),
            'days_until_start': pa.days_until_start,
            'incoming_name'   : pa.user.full_name,
            'role'            : pa.role.display_name,
            'status'          : pa.status,
        })