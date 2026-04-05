from rest_framework import generics, filters, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone

from apps.customers.models import CustomerProfile, CustomerEditLog
from apps.finance.models import CreditAccount, CreditPayment, DailySalesSheet
from apps.customers.credit_engine import CreditEngine, CreditLimitExceeded, CreditAccountNotActive

from .serializers import (
    CustomerSerializer, CustomerListSerializer, CustomerCreateSerializer,
    CreditAccountSerializer, CreditAccountNominateSerializer,
    CreditPaymentSerializer, CreditSettleSerializer,
    CustomerEditLogSerializer,
)


# ── Customer views ────────────────────────────────────────────────────────────

class CustomerListView(generics.ListAPIView):
    queryset           = CustomerProfile.objects.select_related('preferred_branch').all()
    serializer_class   = CustomerListSerializer
    permission_classes = [IsAuthenticated]
    filter_backends    = [filters.SearchFilter]
    search_fields      = ['phone', 'first_name', 'last_name', 'email', 'company_name']

    def get_queryset(self):
        qs     = super().get_queryset()
        params = self.request.query_params

        tier          = params.get('tier')
        is_priority   = params.get('is_priority')
        branch        = params.get('branch')
        customer_type = params.get('customer_type')

        if tier:
            qs = qs.filter(tier=tier)
        if is_priority is not None:
            qs = qs.filter(is_priority=is_priority.lower() == 'true')
        if branch:
            qs = qs.filter(branch_id=branch)
        if customer_type:
            qs = qs.filter(customer_type=customer_type)

        company_name = params.get('company_name')
        if company_name:
            qs = qs.filter(company_name__iexact=company_name)

        phone = params.get('phone')
        if phone:
            qs = qs.filter(phone=phone)

        return qs


class CustomerDetailView(generics.RetrieveUpdateAPIView):
    queryset           = CustomerProfile.objects.select_related('preferred_branch').all()
    serializer_class   = CustomerSerializer
    permission_classes = [IsAuthenticated]


class CustomerCreateView(generics.CreateAPIView):
    serializer_class   = CustomerCreateSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        # Auto-assign branch from the creating user if not provided
        user   = self.request.user
        branch = serializer.validated_data.get('preferred_branch') or getattr(user, 'branch', None)
        serializer.save(branch=branch)


class CustomerLookupView(APIView):
    """
    GET /api/v1/customers/lookup/?phone=<phone>
    Look up a customer by phone number.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        phone = request.query_params.get('phone')
        if not phone:
            return Response(
                {'detail': 'Phone number is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            customer   = CustomerProfile.objects.get(phone=phone)
            serializer = CustomerSerializer(customer)
            return Response(serializer.data)
        except CustomerProfile.DoesNotExist:
            return Response(
                {'detail': 'Customer not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )


# ── Credit Account views ──────────────────────────────────────────────────────

class CreditAccountListView(generics.ListAPIView):
    """
    GET /api/v1/customers/credit/
    Lists credit accounts for the requesting user's branch.
    """
    serializer_class   = CreditAccountSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        branch = getattr(self.request.user, 'branch', None)
        qs     = CreditAccount.objects.select_related(
            'customer', 'branch', 'nominated_by', 'approved_by'
        )
        if branch:
            qs = qs.filter(branch=branch)
        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs


class CreditAccountDetailView(generics.RetrieveAPIView):
    """
    GET /api/v1/customers/credit/<pk>/
    """
    serializer_class   = CreditAccountSerializer
    permission_classes = [IsAuthenticated]
    queryset           = CreditAccount.objects.select_related(
        'customer', 'branch', 'nominated_by', 'approved_by'
    )


class CreditAccountNominateView(APIView):
    """
    POST /api/v1/customers/credit/nominate/
    BM nominates a customer for a credit account.
    Creates account in PENDING status — awaits Belt Manager approval.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CreditAccountNominateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        account = serializer.save(
            nominated_by = request.user,
            nominated_at = timezone.now(),
            status       = CreditAccount.Status.PENDING,
        )

        # Notify Belt Manager
        try:
            from apps.notifications.services import notify
            from apps.accounts.models import CustomUser
            belt_managers = CustomUser.objects.filter(
                role__name='BELT_MANAGER',
                branch__belt=request.user.branch.belt if request.user.branch else None,
            )
            for bm in belt_managers:
                notify(
                    recipient = bm,
                    message   = (
                        f"{request.user.full_name} has nominated "
                        f"{account.customer.display_name} for a credit account "
                        f"(limit: GHS {account.credit_limit}). Please review."
                    ),
                    category  = 'CREDIT',
                    link      = f'/credit/{account.id}/',
                )
        except Exception:
            pass

        return Response(
            CreditAccountSerializer(account).data,
            status=status.HTTP_201_CREATED,
        )


class CreditAccountApproveView(APIView):
    """
    POST /api/v1/customers/credit/<pk>/approve/
    Belt Manager approves a PENDING credit account → sets to ACTIVE.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            account = CreditAccount.objects.get(pk=pk, status=CreditAccount.Status.PENDING)
        except CreditAccount.DoesNotExist:
            return Response(
                {'detail': 'Pending credit account not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        account.status      = CreditAccount.Status.ACTIVE
        account.approved_by = request.user
        account.approved_at = timezone.now()
        account.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])

        # Notify the nominating BM
        try:
            from apps.notifications.services import notify
            notify(
                recipient = account.nominated_by,
                message   = (
                    f"Credit account for {account.customer.display_name} "
                    f"has been approved by {request.user.full_name}. "
                    f"Limit: GHS {account.credit_limit}."
                ),
                category  = 'CREDIT',
                link      = f'/credit/{account.id}/',
            )
        except Exception:
            pass

        return Response(CreditAccountSerializer(account).data)


class CreditAccountSuspendView(APIView):
    """
    POST /api/v1/customers/credit/<pk>/suspend/
    Suspends an active credit account.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            account = CreditAccount.objects.get(pk=pk, status=CreditAccount.Status.ACTIVE)
        except CreditAccount.DoesNotExist:
            return Response(
                {'detail': 'Active credit account not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        reason = request.data.get('reason', '').strip()
        if not reason:
            return Response(
                {'detail': 'Suspension reason is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        account.status            = CreditAccount.Status.SUSPENDED
        account.suspended_at      = timezone.now()
        account.suspended_by      = request.user
        account.suspension_reason = reason
        account.save(update_fields=[
            'status', 'suspended_at', 'suspended_by',
            'suspension_reason', 'updated_at',
        ])

        return Response(CreditAccountSerializer(account).data)


# ── Credit Settlement views ───────────────────────────────────────────────────

class CreditSettleView(APIView):
    """
    POST /api/v1/customers/credit/<pk>/settle/
    Cashier records a settlement payment against a credit account.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            account = CreditAccount.objects.select_related('customer', 'branch').get(pk=pk)
        except CreditAccount.DoesNotExist:
            return Response(
                {'detail': 'Credit account not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = CreditSettleSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data

        # Fetch today's sheet
        try:
            sheet = DailySalesSheet.objects.get(
                pk       = data['sheet_id'],
                status   = 'OPEN',
                branch   = account.branch,
            )
        except DailySalesSheet.DoesNotExist:
            return Response(
                {'detail': 'No open sheet found for this branch.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            payment = CreditEngine.settle(
                credit_account = account,
                amount         = data['amount'],
                method         = data['method'],
                sheet          = sheet,
                cashier        = request.user,
                reference      = data.get('reference', ''),
                notes          = data.get('notes', ''),
            )
        except CreditAccountNotActive as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            CreditPaymentSerializer(payment).data,
            status=status.HTTP_201_CREATED,
        )


class CreditPaymentHistoryView(generics.ListAPIView):
    """
    GET /api/v1/customers/credit/<pk>/payments/
    Lists all settlement payments for a credit account.
    """
    serializer_class   = CreditPaymentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return CreditPayment.objects.filter(
            credit_account_id=self.kwargs['pk']
        ).select_related('credit_account__customer', 'received_by').order_by('-created_at')

class CustomerEditView(APIView):
    """
    PATCH /api/v1/customers/<pk>/edit/
    BM edits allowed fields on a customer profile.
    Every change is logged to CustomerEditLog.
    """
    permission_classes = [IsAuthenticated]

    EDITABLE_FIELDS = {
        'INDIVIDUAL'  : ['first_name', 'last_name', 'phone', 'email', 'address'],
        'BUSINESS'    : ['company_name', 'first_name', 'last_name', 'phone', 'email', 'address'],
        'INSTITUTION' : ['company_name', 'institution_subtype', 'first_name', 'last_name', 'phone', 'email', 'address'],
    }

    def patch(self, request, pk):
        try:
            customer = CustomerProfile.objects.get(pk=pk)
        except CustomerProfile.DoesNotExist:
            return Response(
                {'detail': 'Customer not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        allowed = self.EDITABLE_FIELDS.get(customer.customer_type, [])
        errors  = {}
        changes = []

        for field, new_value in request.data.items():
            if field not in allowed:
                errors[field] = f'Field "{field}" is not editable.'
                continue

            old_value = str(getattr(customer, field, '') or '')
            new_value = str(new_value or '').strip()

            if old_value == new_value:
                continue

            # Phone uniqueness check
            if field == 'phone':
                if CustomerProfile.objects.filter(phone=new_value).exclude(pk=pk).exists():
                    errors['phone'] = 'A customer with this phone number already exists.'
                    continue

            setattr(customer, field, new_value)
            changes.append(CustomerEditLog(
                customer   = customer,
                changed_by = request.user,
                field_name = field,
                old_value  = old_value,
                new_value  = new_value,
            ))

        if errors:
            return Response(errors, status=status.HTTP_400_BAD_REQUEST)

        if changes:
            customer.save()
            CustomerEditLog.objects.bulk_create(changes)

        return Response(CustomerSerializer(customer).data)


class CustomerEditLogView(generics.ListAPIView):
    """
    GET /api/v1/customers/<pk>/edit-log/
    Returns the full audit trail for a customer profile.
    """
    serializer_class   = CustomerEditLogSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return CustomerEditLog.objects.filter(
            customer_id=self.kwargs['pk']
        ).select_related('changed_by')