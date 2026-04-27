from rest_framework import generics, filters, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.pagination import PageNumberPagination
from rest_framework.exceptions import ValidationError

from apps.customers.models import CustomerProfile
from apps.finance.models import CreditAccount, CreditPayment, DailySalesSheet
from apps.customers.credit_engine import CreditEngine, CreditLimitExceeded, CreditAccountNotActive

from apps.customers.selectors import (
    get_customer_list,
    get_customer_by_id,
    get_customer_by_phone,
    get_customer_edit_log,
    get_credit_accounts,
    get_credit_account_by_id,
)
from apps.customers.services import (
    create_customer,
    edit_customer,
    nominate_credit,
    CustomerAlreadyExists,
    EmployeePhoneConflict,
)

from .serializers import (
    CustomerSerializer, CustomerListSerializer, CustomerCreateSerializer,
    CreditAccountSerializer, CreditAccountNominateSerializer,
    CreditPaymentSerializer, CreditSettleSerializer,
    CustomerEditLogSerializer,
)


# ── Pagination ────────────────────────────────────────────────────────────────

class CustomerPagination(PageNumberPagination):
    page_size             = 20
    page_size_query_param = 'page_size'
    max_page_size         = 200


# ── Customer views ────────────────────────────────────────────────────────────

class CustomerListView(generics.ListAPIView):
    serializer_class   = CustomerListSerializer
    permission_classes = [IsAuthenticated]
    filter_backends    = [filters.SearchFilter]
    search_fields      = ['phone', 'secondary_phone', 'first_name', 'last_name', 'email', 'company_name']
    pagination_class   = CustomerPagination

    def get_queryset(self):
        p = self.request.query_params
        return get_customer_list(
            user          = self.request.user,
            customer_type = p.get('customer_type'),
            tier          = p.get('tier'),
            is_priority   = (
                p.get('is_priority', '').lower() == 'true'
                if 'is_priority' in p else None
            ),
            branch_id     = p.get('branch'),
            company_name  = p.get('company_name'),
            phone         = p.get('phone'),
        )


class CustomerDetailView(generics.RetrieveUpdateAPIView):
    serializer_class   = CustomerSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return get_customer_by_id(pk=self.kwargs['pk'])


class CustomerCreateView(generics.CreateAPIView):
    serializer_class   = CustomerCreateSerializer
    permission_classes = [IsAuthenticated]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            customer = create_customer(user=request.user, data=serializer.validated_data)
        except CustomerAlreadyExists as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except EmployeePhoneConflict as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            CustomerSerializer(customer).data,
            status=status.HTTP_201_CREATED,
        )


class CustomerLookupView(APIView):
    """
    GET /api/v1/customers/lookup/?phone=<phone>
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
            customer = get_customer_by_phone(phone=phone)
            return Response(CustomerSerializer(customer).data)
        except CustomerProfile.DoesNotExist:
            return Response(
                {'detail': 'Customer not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )


class CustomerEditView(APIView):
    """
    PATCH /api/v1/customers/<pk>/edit/
    """
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        try:
            customer = edit_customer(pk=pk, user=request.user, data=request.data)
        except CustomerProfile.DoesNotExist:
            return Response(
                {'detail': 'Customer not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        except ValidationError as e:
            return Response(e.detail, status=status.HTTP_400_BAD_REQUEST)
        return Response(CustomerSerializer(customer).data)


class CustomerEditLogView(generics.ListAPIView):
    """
    GET /api/v1/customers/<pk>/edit-log/
    """
    serializer_class   = CustomerEditLogSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return get_customer_edit_log(pk=self.kwargs['pk'])


# ── Credit Account views ──────────────────────────────────────────────────────

class CreditAccountListView(generics.ListAPIView):
    serializer_class   = CreditAccountSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return get_credit_accounts(
            user   = self.request.user,
            status = self.request.query_params.get('status'),
        )


class CreditAccountDetailView(generics.RetrieveAPIView):
    serializer_class   = CreditAccountSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return get_credit_account_by_id(pk=self.kwargs['pk'])


class CreditAccountNominateView(APIView):
    """
    POST /api/v1/customers/credit/nominate/
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CreditAccountNominateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            account = nominate_credit(
                customer_pk   = serializer.validated_data['customer'].id,
                user          = request.user,
                credit_limit  = serializer.validated_data['credit_limit'],
                payment_terms = serializer.validated_data['payment_terms'],
                account_type  = serializer.validated_data.get('account_type', 'INDIVIDUAL'),
                contact_person= serializer.validated_data.get('contact_person', ''),
            )
        except CustomerProfile.DoesNotExist:
            return Response(
                {'detail': 'Customer not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(
            CreditAccountSerializer(account).data,
            status=status.HTTP_201_CREATED,
        )


class CreditAccountApproveView(APIView):
    """
    POST /api/v1/customers/credit/<pk>/approve/
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            account = get_credit_account_by_id(pk=pk, status=CreditAccount.Status.PENDING)
        except CreditAccount.DoesNotExist:
            return Response(
                {'detail': 'Pending credit account not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        from django.utils import timezone
        account.status      = CreditAccount.Status.ACTIVE
        account.approved_by = request.user
        account.approved_at = timezone.now()
        account.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])

        try:
            from apps.notifications.services import notify
            notify(
                recipient=account.nominated_by,
                message=(
                    f"Credit account for {account.customer.display_name} "
                    f"has been approved by {request.user.full_name}. "
                    f"Limit: GHS {account.credit_limit}."
                ),
                category='CREDIT',
                link=f'/credit/{account.id}/',
            )
        except Exception:
            pass

        return Response(CreditAccountSerializer(account).data)


class CreditAccountSuspendView(APIView):
    """
    POST /api/v1/customers/credit/<pk>/suspend/
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            account = get_credit_account_by_id(pk=pk, status=CreditAccount.Status.ACTIVE)
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

        from django.utils import timezone
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

        try:
            sheet = DailySalesSheet.objects.get(
                pk     = data['sheet_id'],
                status = 'OPEN',
                branch = account.branch,
            )
        except DailySalesSheet.DoesNotExist:
            return Response(
                {'detail': 'No open sheet found for this branch.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            payment = CreditEngine.settle(
                credit_account=account,
                amount        =data['amount'],
                method        =data['method'],
                sheet         =sheet,
                cashier       =request.user,
                reference     =data.get('reference', ''),
                notes         =data.get('notes', ''),
            )
        except (CreditAccountNotActive, ValueError) as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            CreditPaymentSerializer(payment).data,
            status=status.HTTP_201_CREATED,
        )


class CreditPaymentHistoryView(generics.ListAPIView):
    """
    GET /api/v1/customers/credit/<pk>/payments/
    """
    serializer_class   = CreditPaymentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return CreditPayment.objects.filter(
            credit_account_id=self.kwargs['pk']
        ).select_related('credit_account__customer', 'received_by').order_by('-created_at')