from asyncio.log import logger

from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone

from apps.finance.models import (
    DailySalesSheet,
    CashierFloat,
    PettyCash,
    POSTransaction,
    Receipt,
    CreditAccount,
    CreditPayment,
    BranchTransferCredit,
    Invoice,
    InvoiceLineItem,
    WeeklyReport,
)
from apps.finance.models.invoice import Invoice
from apps.finance.sheet_engine import SheetEngine
from apps.finance.receipt_engine import ReceiptEngine
from apps.finance.credit_engine import CreditEngine
from apps.finance.models import MonthlyClose
from apps.finance.monthly_close_engine import MonthlyCloseEngine

from apps.core.finance_scope import get_finance_scope, REGIONAL_ROLES, NATIONAL_ROLES

FINANCE_ROLES = (
    'FINANCE',
    'NATIONAL_FINANCE_HEAD',
    'NATIONAL_FINANCE_DEPUTY',
    'BELT_FINANCE_OFFICER',
    'BELT_FINANCE_DEPUTY',
    'REGIONAL_FINANCE_OFFICER',
    'REGIONAL_FINANCE_DEPUTY',
    'SUPER_ADMIN',
)

from .serializers import (
    DailySalesSheetListSerializer,
    DailySalesSheetDetailSerializer,
    DailySalesSheetNotesSerializer,
    CashierFloatSerializer,
    CashierFloatSetSerializer,
    CashierFloatCloseSerializer,
    PettyCashSerializer,
    PettyCashCreateSerializer,
    POSTransactionSerializer,
    POSSettleSerializer,
    ReceiptSerializer,
    CreditAccountSerializer,
    CreditAccountCreateSerializer,
    CreditAccountApproveSerializer,
    CreditPaymentSerializer,
    CreditSettlementSerializer,
    BranchTransferCreditSerializer,
    CashierSignOffSerializer,
    InvoiceSerializer,
    InvoiceCreateSerializer,
    WeeklyReportListSerializer,
    WeeklyReportDetailSerializer,
    WeeklyReportNotesSerializer,
)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Pagination
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
from rest_framework.pagination import PageNumberPagination

class StandardResultsPagination(PageNumberPagination):
    page_size            = 10
    page_size_query_param = 'page_size'
    max_page_size        = 100

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Daily Sales Sheet
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class DailySalesSheetListView(generics.ListAPIView):
    """
    GET /api/v1/finance/sheets/
    Returns sheets for the requesting user's branch.
    Belt/Region managers see all sheets across their scope.
    """
    serializer_class   = DailySalesSheetListSerializer
    permission_classes = [IsAuthenticated]
    pagination_class   = None

    def get_queryset(self):
        user = self.request.user
        qs   = DailySalesSheet.objects.select_related(
            'branch', 'opened_by', 'closed_by'
        )

        if hasattr(user, 'branch') and user.branch:
            qs = qs.filter(branch=user.branch)

        date_param = self.request.query_params.get('date')
        if date_param:
            qs = qs.filter(date=date_param)

        year_param = self.request.query_params.get('year')
        if year_param:
            qs = qs.filter(date__year=year_param)

        period = self.request.query_params.get('period')
        if period:
            from django.utils import timezone
            from datetime import timedelta
            now = timezone.localdate()
            since = {
                'day':   now,
                'week':  now - timedelta(days=now.weekday()),
                'month': now.replace(day=1),
                'year':  now.replace(month=1, day=1),
            }.get(period)
            if since:
                qs = qs.filter(date__gte=since)

        return qs


class DailySalesSheetDetailView(generics.RetrieveAPIView):
    """
    GET /api/v1/finance/sheets/<id>/
    Full sheet detail including floats and petty cash.
    """
    serializer_class   = DailySalesSheetDetailSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs   = DailySalesSheet.objects.select_related(
            'branch', 'opened_by', 'closed_by'
        ).prefetch_related(
            'cashier_floats', 'petty_cash_entries'
        )
        if hasattr(user, 'branch') and user.branch:
            qs = qs.filter(branch=user.branch)
        return qs


class DailySalesSheetTodayView(APIView):
    """
    GET /api/v1/finance/sheets/today/
    Returns today's sheet for the user's branch.
    Creates one if it doesn't exist (fallback open).

    Returns serialized sheet data only â€” no live total injection.
    Live vs frozen revenue is handled by SheetSummaryService via
    the /summary/ endpoint. This view remains a thin identity fetch.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if not hasattr(user, 'branch') or not user.branch:
            return Response(
                {'detail': 'User has no branch assigned.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        sheet, _ = SheetEngine(user.branch).get_or_open_today(
            opened_by=user,
        )

        if sheet is None:
            return Response(
                {'detail': 'No sheet today â€” branch may be closed (Sunday).'},
                status=status.HTTP_404_NOT_FOUND,
            )

        data = DailySalesSheetDetailSerializer(
            sheet, context={'request': request}
        ).data
        return Response(data)

class TodaySummaryView(APIView):
    """
    GET /api/v1/finance/sheets/today/summary/
    Single-call endpoint for the BM portal day sheet.
    Opens today's sheet if needed, then returns the full
    SheetSummaryService payload â€” live revenue, jobs, inventory, alerts.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.finance.services.sheet_summary_service import SheetSummaryService

        user = request.user
        if not hasattr(user, 'branch') or not user.branch:
            return Response(
                {'detail': 'User has no branch assigned.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        sheet, _ = SheetEngine(user.branch).get_or_open_today(opened_by=user)

        if sheet is None:
            return Response(
                {'detail': 'No sheet today â€” branch may be closed (Sunday).'},
                status=status.HTTP_404_NOT_FOUND,
            )

        summary = SheetSummaryService.get_summary(sheet, sheet.branch)
        return Response(summary)

class DailySalesSheetSummaryView(APIView):
    """
    GET /api/v1/finance/sheets/<pk>/summary/
    Unified day sheet summary for the BM portal.

    Returns one payload covering: revenue (live or frozen),
    job counts, registration rate, pace, inventory snapshot,
    and outstanding alerts. Replaces the multi-API client-side
    join previously done in dashboard.js.

    Access: branch-scoped â€” BM can only access own branch sheets.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        from apps.finance.services.sheet_summary_service import SheetSummaryService

        try:
            sheet = DailySalesSheet.objects.select_related(
                'branch', 'opened_by', 'closed_by'
            ).get(pk=pk)
        except DailySalesSheet.DoesNotExist:
            return Response(
                {'detail': 'Sheet not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Branch-scope enforcement
        user_branch = getattr(request.user, 'branch', None)
        if user_branch and sheet.branch != user_branch:
            return Response(
                {'detail': 'Access denied.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        summary = SheetSummaryService.get_summary(sheet, sheet.branch)
        return Response(summary)
    
    
class DailySalesSheetNotesView(APIView):
    """
    PATCH /api/v1/finance/sheets/<id>/notes/
    BM can add or update notes on a sheet.
    Numbers are never touched.
    """
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        try:
            sheet = DailySalesSheet.objects.get(pk=pk)
        except DailySalesSheet.DoesNotExist:
            return Response(
                {'detail': 'Sheet not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if sheet.status != DailySalesSheet.Status.OPEN:
            return Response(
                {'detail': 'Cannot edit a closed sheet.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = DailySalesSheetNotesSerializer(
            sheet, data=request.data, partial=True
        )
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(f"Invoice create data: {serializer.validated_data}")

        serializer.save()
        return Response(serializer.data)


class DailySalesSheetCloseView(APIView):
    """
    POST /api/v1/finance/sheets/<id>/close/
    BM closes the daily sheet.
    All gates enforced by FloatEngine before SheetEngine closes.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        from apps.finance.models import DailySalesSheet
        from apps.finance.sheet_engine import SheetEngine
        from apps.finance.float_engine import FloatEngine

        try:
            sheet = DailySalesSheet.objects.select_related('branch').get(
                pk     = pk,
                branch = request.user.branch,
            )
        except DailySalesSheet.DoesNotExist:
            return Response(
                {'detail': 'Sheet not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if sheet.status != DailySalesSheet.Status.OPEN:
            return Response(
                {'detail': f"Sheet is already {sheet.status}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        errors = []

        # â”€â”€ Gate 1: All cashiers signed off â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        signoff_gate = FloatEngine.validate_signoff_gate(sheet)
        if not signoff_gate['passed']:
            errors.extend(signoff_gate['errors'])

        # â”€â”€ Gate 2: No pending instant payments â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        from apps.jobs.models import Job
        pending = Job.objects.filter(
            daily_sheet  = sheet,
            status       = Job.PENDING_PAYMENT,
            job_type     = 'INSTANT',
        ).count()
        if pending:
            errors.append(
                f"{pending} instant job(s) still pending payment. "
                f"Resolve before closing."
            )

        # â”€â”€ Stage tomorrow's floats BEFORE Gate 3 â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        from apps.accounts.models import CustomUser
        from datetime import timedelta
        from decimal import Decimal

        floats_data = request.data.get('floats', [])
        tomorrow    = sheet.date + timedelta(days=1)
        if tomorrow.weekday() == 6:
            tomorrow = tomorrow + timedelta(days=1)

        for f in floats_data:
            try:
                cashier = CustomUser.objects.get(
                    pk     = f['cashier_id'],
                    branch = sheet.branch,
                )
                FloatEngine.stage_float(
                    cashier     = cashier,
                    amount      = Decimal(str(f['opening_float'])),
                    set_by      = request.user,
                    target_date = tomorrow,
                    branch      = sheet.branch,
                )
            except Exception:
                pass

        # â”€â”€ Gate 3: Tomorrow's float set â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        float_gate = FloatEngine.validate_tomorrow_float_gate(sheet)
        if not float_gate['passed']:
            errors.extend(float_gate['errors'])

        if errors:
            return Response(
                {
                    'detail': 'Sheet cannot be closed.',
                    'errors': errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # â”€â”€ All gates passed â€” close the sheet â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        try:
            engine = SheetEngine(sheet.branch)
            closed = engine.close_sheet(
                sheet     = sheet,
                closed_by = request.user,
                auto      = False,
            )
        except ValueError as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from apps.finance.serializers import DailySalesSheetListSerializer
        return Response(DailySalesSheetListSerializer(closed).data)

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Cashier Float
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class CashierFloatSetView(APIView):
    """
    POST /api/v1/finance/sheets/<id>/floats/set/
    BM sets the opening float for a cashier at day start.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            sheet = DailySalesSheet.objects.get(pk=pk)
        except DailySalesSheet.DoesNotExist:
            return Response(
                {'detail': 'Sheet not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = CashierFloatSetSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(f"Invoice create data: {serializer.validated_data}")

        from apps.accounts.models import CustomUser
        from django.utils import timezone

        try:
            cashier = CustomUser.objects.get(
                pk=serializer.validated_data['cashier_id']
            )
        except CustomUser.DoesNotExist:
            return Response(
                {'detail': 'Cashier not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        float_record, created = CashierFloat.objects.get_or_create(
            daily_sheet=sheet,
            cashier=cashier,
            defaults={
                'opening_float' : serializer.validated_data['opening_float'],
                'float_set_by'  : request.user,
                'float_set_at'  : timezone.now(),
            },
        )

        if not created:
            return Response(
                {'detail': 'Float already set for this cashier today.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            CashierFloatSerializer(float_record).data,
            status=status.HTTP_201_CREATED,
        )


class CashierFloatCloseView(APIView):
    """
    POST /api/v1/finance/floats/<id>/close/
    Cashier submits their closing cash count.
    Variance is computed automatically.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            float_record = CashierFloat.objects.get(pk=pk)
        except CashierFloat.DoesNotExist:
            return Response(
                {'detail': 'Float record not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = CashierFloatCloseSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        float_record.closing_cash   = serializer.validated_data['closing_cash']
        float_record.variance_notes = serializer.validated_data.get(
            'variance_notes', ''
        )
        float_record.compute_variance()
        float_record.save(update_fields=[
            'closing_cash', 'variance_notes', 'variance', 'updated_at'
        ])

        return Response(CashierFloatSerializer(float_record).data)

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Cashier Sign-Off
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class CashierSignOffView(APIView):
    """
    POST /api/v1/finance/floats/<id>/sign-off/
    Cashier submits closing cash, variance notes, shift notes.
    Handles both EOD sign-off and mid-day handover.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        from apps.finance.models import CashierFloat
        from apps.finance.float_engine import FloatEngine

        try:
            float_record = CashierFloat.objects.select_related(
                'cashier', 'daily_sheet'
            ).get(pk=pk, cashier=request.user)
        except CashierFloat.DoesNotExist:
            return Response(
                {'detail': 'Float record not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if float_record.is_signed_off:
            return Response(
                {'detail': 'Already signed off.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        is_handover  = request.data.get('is_handover', False)
        is_overtime  = request.data.get('is_overtime', False)
        is_cover     = request.data.get('is_cover', False)

        # â”€â”€ Mid-day handover â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if is_handover:
            handover_amount = request.data.get('handover_amount', 0)
            breakdown       = request.data.get('breakdown', {})
            shift_notes     = request.data.get('shift_notes', '')

            result = FloatEngine.mid_day_handover(
                float_record    = float_record,
                handover_amount = handover_amount,
                breakdown       = breakdown,
                signed_off_by   = request.user,
                shift_notes     = shift_notes,
            )

            if not result['ok']:
                return Response(
                    {'detail': result['error']},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            return Response({
                'detail'         : 'Handover recorded. Next cashier float staged.',
                'is_handover'    : True,
                'handover_amount': str(result['float'].handover_float),
                'next_float_id'  : result['next_staged'].pk,
            })

        # â”€â”€ Overtime extension â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if is_overtime or is_cover:
            overtime_until  = request.data.get('overtime_until')
            overtime_reason = request.data.get('overtime_reason', '')
            cover_until     = request.data.get('cover_until')

            from django.utils import timezone
            float_record.is_overtime     = is_overtime
            float_record.overtime_reason = overtime_reason
            float_record.overtime_until  = overtime_until
            float_record.is_cover        = is_cover
            float_record.cover_until     = cover_until

            if request.data.get('covering_for_id'):
                from apps.accounts.models import CustomUser
                try:
                    float_record.covering_for = CustomUser.objects.get(
                        pk=request.data['covering_for_id']
                    )
                except CustomUser.DoesNotExist:
                    return Response(
                        {'detail': 'User to cover not found.'},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

            float_record.save(update_fields=[
                'is_overtime', 'overtime_reason', 'overtime_until',
                'is_cover', 'covering_for', 'cover_until', 'updated_at',
            ])

            return Response({
                'detail'        : 'Shift extended.',
                'is_overtime'   : float_record.is_overtime,
                'overtime_until': float_record.overtime_until,
                'is_cover'      : float_record.is_cover,
                'cover_until'   : float_record.cover_until,
            })

        # â”€â”€ EOD sign-off â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        closing_cash   = request.data.get('closing_cash', 0)
        breakdown      = request.data.get('breakdown', {})
        variance_notes = request.data.get('variance_notes', '')
        shift_notes    = request.data.get('shift_notes', '')

        result = FloatEngine.sign_off(
            float_record   = float_record,
            closing_cash   = closing_cash,
            breakdown      = breakdown,
            variance_notes = variance_notes,
            shift_notes    = shift_notes,
            signed_off_by  = request.user,
            is_overtime    = False,
        )

        if not result['ok']:
            return Response(
                {'detail': result['error']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from apps.finance.serializers import CashierFloatSerializer
        return Response(CashierFloatSerializer(result['float']).data)


def _compute_expected_cash(float_record):
    """
    Expected cash = opening float + all cash payments collected by this cashier today.
    This is computed live so the sign-off wizard shows the correct figure
    before the cashier closes their float.
    """
    from django.db.models import Sum
    from decimal import Decimal

    cash_collected = Receipt.objects.filter(
        cashier      = float_record.cashier,
        daily_sheet  = float_record.daily_sheet,
        payment_method = 'CASH',
        is_void      = False,
    ).aggregate(t=Sum('amount_paid'))['t'] or Decimal('0.00')

    return float_record.opening_float + cash_collected


class CashierShiftStatusView(APIView):
    """
    GET /api/v1/finance/cashier/shift-status/
    Returns current shift state for the logged-in cashier.
    Polled every 60s by the cashier portal.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.utils import timezone
        from apps.hr.shift_engine import ShiftEngine as HRShiftEngine
        from apps.finance.float_engine import FloatEngine
        from datetime import datetime as dt

        user   = request.user
        branch = getattr(user, 'branch', None)

        if not branch:
            return Response(
                {'detail': 'No branch assigned.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        today = timezone.localdate()
        now   = timezone.now()

        # â”€â”€ Float status via FloatEngine â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        float_status = FloatEngine.get_float_status(
            cashier = user,
            branch  = branch,
            date    = today,
        )

        # â”€â”€ Resolve sheet_number â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        from apps.finance.models import DailySalesSheet as DSS
        _sheet_number = ''
        if float_status.get('sheet_id'):
            try:
                _sheet_number = DSS.objects.filter(
                    pk=float_status['sheet_id']
                ).values_list('sheet_number', flat=True).first() or ''
            except Exception:
                pass

        # â”€â”€ Signed off â€” return immediately â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if float_status['float_status'] == 'SIGNED_OFF':
            try:
                _fr = CashierFloat.objects.get(pk=float_status['float_id'])
                _exp = str(_fr.expected_cash)
            except Exception:
                _exp = '0'
            return Response({
                'has_shift'        : True,
                'float_status'     : 'SIGNED_OFF',
                'float_id'         : float_status['float_id'],
                'sheet_id'         : float_status['sheet_id'],
                'sheet_number'     : _sheet_number,
                'opening_float'    : float_status['opening_float'],
                'opening_breakdown': float_status['opening_breakdown'],
                'expected_cash'    : _exp,
                'shift_end'        : None,
                'minutes_remaining': 0,
                'should_prompt'    : False,
                'should_lock'      : True,
                'is_signed_off'    : True,
                'is_overtime'      : False,
                'overtime_until'   : None,
                'is_cover'         : False,
                'cover_until'      : None,
            })

        # â”€â”€ No float â€” return immediately â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if float_status['float_status'] == 'NO_FLOAT':
            return Response({
                'has_shift'        : False,
                'float_status'     : 'NO_FLOAT',
                'float_id'         : None,
                'sheet_id'         : None,
                'sheet_number'     : '',
                'opening_float'    : None,
                'opening_breakdown': None,
                'shift_end'        : None,
                'minutes_remaining': None,
                'should_prompt'    : False,
                'should_lock'      : False,
                'is_signed_off'    : False,
                'is_overtime'      : False,
                'overtime_until'   : None,
                'is_cover'         : False,
                'cover_until'      : None,
            })

        # â”€â”€ Pending acknowledgement â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if float_status['float_status'] == 'PENDING_ACK':
            return Response({
                'has_shift'        : True,
                'float_status'     : 'PENDING_ACK',
                'float_id'         : float_status['float_id'],
                'sheet_id'         : float_status['sheet_id'],
                'sheet_number'     : _sheet_number,
                'opening_float'    : float_status['opening_float'],
                'opening_breakdown': float_status['opening_breakdown'],
                'shift_end'        : None,
                'minutes_remaining': None,
                'should_prompt'    : False,
                'should_lock'      : False,
                'is_signed_off'    : False,
                'is_overtime'      : False,
                'overtime_until'   : None,
                'is_cover'         : False,
                'cover_until'      : None,
            })

        # â”€â”€ Active shift â€” compute timing â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        from apps.finance.models import CashierFloat

        float_record = None
        if float_status['float_id']:
            try:
                float_record = CashierFloat.objects.get(
                    pk = float_status['float_id']
                )
            except CashierFloat.DoesNotExist:
                pass

        # Overtime active
        if (float_record and float_record.is_overtime
                and float_record.overtime_until):
            delta          = float_record.overtime_until - now
            mins_remaining = max(0, int(delta.total_seconds() / 60))
            return Response({
                'has_shift'        : True,
                'float_status'     : 'ACTIVE',
                'float_id'         : float_status['float_id'],
                'sheet_id'         : float_status['sheet_id'],
                'opening_float'    : float_status['opening_float'],
                'opening_breakdown': float_status['opening_breakdown'],
                'sheet_number'     : _sheet_number,
                'shift_end'        : float_record.overtime_until.time(),
                'minutes_remaining': mins_remaining,
                'should_prompt'    : mins_remaining <= 60,
                'should_lock'      : mins_remaining <= 0,
                'is_signed_off'    : False,
                'is_overtime'      : True,
                'overtime_until'   : float_record.overtime_until,
                'is_cover'         : float_record.is_cover,
                'cover_until'      : float_record.cover_until,
            })

        # Normal active shift â€” get role schedule
        cash_schedule  = HRShiftEngine(branch).get_role_schedule(
            'CASHIER', target_date=today
        )
        signoff_dt     = dt.fromisoformat(cash_schedule['signoff_at'])
        delta          = signoff_dt - now
        mins_remaining = max(0, int(delta.total_seconds() / 60))
        shift_end      = dt.fromisoformat(cash_schedule['shift_end']).time()

        float_status_val = float_status['float_status']
        if mins_remaining <= 0 and float_status_val == 'ACTIVE':
            float_status_val = 'PENDING_SIGNOFF'

        return Response({
            'has_shift'        : True,
            'float_status'     : float_status_val,
            'float_id'         : float_status['float_id'],
            'sheet_id'         : float_status['sheet_id'],
            'sheet_number'     : _sheet_number,
            'opening_float'    : float_status['opening_float'],
            'opening_breakdown': float_status['opening_breakdown'],
            'expected_cash'    : str(_compute_expected_cash(float_record)) if float_record else '0',
            'shift_end'        : shift_end,
            'minutes_remaining': mins_remaining,
            'should_prompt'    : mins_remaining <= 60,
            'should_lock'      : mins_remaining <= 0,
            'is_signed_off'    : False,
            'is_overtime'      : float_record.is_overtime if float_record else False,
            'overtime_until'   : float_record.overtime_until if float_record else None,
            'is_cover'         : float_record.is_cover if float_record else False,
            'cover_until'      : float_record.cover_until if float_record else None,
        })
    
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Petty Cash
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class CashierHistoryView(APIView):
    """
    GET /api/v1/finance/cashier/history/
    Returns the logged-in cashier's personal collection history.

    Query params:
      ?level=year                     â€” yearly totals
      ?level=month&year=2026          â€” monthly breakdown for a year
      ?level=week&year=2026&month=3   â€” weekly breakdown for a month
      ?level=day&year=2026&month=3&week=12 â€” daily breakdown for a week (ISO week)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.db.models import Sum, Count, Q
        from django.db.models.functions import (
            TruncYear, TruncMonth, TruncWeek, TruncDay,
            ExtractYear, ExtractMonth, ExtractWeek,
        )
        from django.utils import timezone

        user  = request.user
        level = request.query_params.get('level', 'year')

        qs = Receipt.objects.filter(
            cashier  = user,
            is_void  = False,
        ).select_related('daily_sheet')

        # â”€â”€ Apply drill-down filters â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        year_param  = request.query_params.get('year')
        month_param = request.query_params.get('month')
        week_param  = request.query_params.get('week')

        if year_param:
            qs = qs.filter(created_at__year=int(year_param))
        if month_param:
            qs = qs.filter(created_at__month=int(month_param))
        if week_param:
            qs = qs.filter(created_at__week=int(week_param))

        # â”€â”€ Aggregate per method â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        def _totals(queryset):
            return {
                'cash' : float(queryset.filter(payment_method='CASH').aggregate(
                    t=Sum('amount_paid'))['t'] or 0),
                'momo' : float(queryset.filter(payment_method='MOMO').aggregate(
                    t=Sum('amount_paid'))['t'] or 0),
                'pos'  : float(queryset.filter(payment_method='POS').aggregate(
                    t=Sum('amount_paid'))['t'] or 0),
                'count': queryset.count(),
            }

        # â”€â”€ Year level â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if level == 'year':
            years = (
                qs.annotate(yr=ExtractYear('created_at'))
                  .values('yr')
                  .distinct()
                  .order_by('-yr')
            )
            result = []
            for row in years:
                y   = row['yr']
                sub = qs.filter(created_at__year=y)
                t   = _totals(sub)
                result.append({
                    'label'    : str(y),
                    'year'     : y,
                    'cash'     : t['cash'],
                    'momo'     : t['momo'],
                    'pos'      : t['pos'],
                    'total'    : t['cash'] + t['momo'] + t['pos'],
                    'count'    : t['count'],
                })
            return Response({'level': 'year', 'results': result})

        # â”€â”€ Month level â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if level == 'month':
            import calendar
            months = (
                qs.annotate(mo=ExtractMonth('created_at'))
                  .values('mo')
                  .distinct()
                  .order_by('-mo')
            )
            result = []
            for row in months:
                m   = row['mo']
                sub = qs.filter(created_at__month=m)
                t   = _totals(sub)
                result.append({
                    'label'    : calendar.month_name[m],
                    'month'    : m,
                    'year'     : int(year_param) if year_param else None,
                    'cash'     : t['cash'],
                    'momo'     : t['momo'],
                    'pos'      : t['pos'],
                    'total'    : t['cash'] + t['momo'] + t['pos'],
                    'count'    : t['count'],
                })
            return Response({'level': 'month', 'results': result})

        # â”€â”€ Week level â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if level == 'week':
            weeks = (
                qs.annotate(wk=ExtractWeek('created_at'))
                  .values('wk')
                  .distinct()
                  .order_by('-wk')
            )
            result = []
            for row in weeks:
                w   = row['wk']
                sub = qs.filter(created_at__week=w)
                t   = _totals(sub)
                result.append({
                    'label' : f'Week {w}',
                    'week'  : w,
                    'month' : int(month_param) if month_param else None,
                    'year'  : int(year_param)  if year_param  else None,
                    'cash'  : t['cash'],
                    'momo'  : t['momo'],
                    'pos'   : t['pos'],
                    'total' : t['cash'] + t['momo'] + t['pos'],
                    'count' : t['count'],
                })
            return Response({'level': 'week', 'results': result})

        # â”€â”€ Day level â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if level == 'day':
            from django.db.models.functions import ExtractDay
            days = (
                qs.annotate(
                    dy=TruncDay('created_at')
                )
                .values('dy')
                .distinct()
                .order_by('-dy')
            )
            result = []
            for row in days:
                d   = row['dy']
                sub = qs.filter(
                    created_at__date=d.date()
                )
                t   = _totals(sub)
                result.append({
                    'label'    : d.strftime('%a, %d %b %Y'),
                    'date'     : d.date().isoformat(),
                    'cash'     : t['cash'],
                    'momo'     : t['momo'],
                    'pos'      : t['pos'],
                    'total'    : t['cash'] + t['momo'] + t['pos'],
                    'count'    : t['count'],
                })
            return Response({'level': 'day', 'results': result})

        return Response(
            {'detail': 'Invalid level. Use year, month, week, or day.'},
            status=400,
        )

class PettyCashCreateView(APIView):
    """
    POST /api/v1/finance/sheets/<id>/petty-cash/
    Record a petty cash disbursement â€” requires BM approval.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            sheet = DailySalesSheet.objects.get(pk=pk)
        except DailySalesSheet.DoesNotExist:
            return Response(
                {'detail': 'Sheet not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if sheet.status != DailySalesSheet.Status.OPEN:
            return Response(
                {'detail': 'Cannot record petty cash on a closed sheet.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = PettyCashCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            float_record = CashierFloat.objects.get(
                pk=serializer.validated_data['cashier_float_id'],
                daily_sheet=sheet,
            )
        except CashierFloat.DoesNotExist:
            return Response(
                {'detail': 'Cashier float not found for this sheet.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        from django.utils import timezone

        entry = PettyCash.objects.create(
            daily_sheet   = sheet,
            cashier_float = float_record,
            amount        = serializer.validated_data['amount'],
            category      = serializer.validated_data['category'],
            purpose       = serializer.validated_data['purpose'],
            approved_by   = request.user,
            approved_at   = timezone.now(),
            recorded_by   = request.user,
        )

        return Response(
            PettyCashSerializer(entry).data,
            status=status.HTTP_201_CREATED,
        )


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# POS Transactions
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class POSTransactionListView(generics.ListAPIView):
    """
    GET /api/v1/finance/pos/
    Returns POS transactions for the user's branch.
    Filter by status: ?status=PENDING | SETTLED | REVERSED
    """
    serializer_class   = POSTransactionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user   = self.request.user
        qs     = POSTransaction.objects.select_related('job', 'cashier')
        status_param = self.request.query_params.get('status')

        if hasattr(user, 'branch') and user.branch:
            qs = qs.filter(job__branch=user.branch)
        if status_param:
            qs = qs.filter(status=status_param)

        return qs


class POSTransactionSettleView(APIView):
    """
    POST /api/v1/finance/pos/<id>/settle/
    Mark a POS transaction as settled by the bank.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            txn = POSTransaction.objects.get(pk=pk)
        except POSTransaction.DoesNotExist:
            return Response(
                {'detail': 'POS transaction not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if txn.status != POSTransaction.Status.PENDING:
            return Response(
                {'detail': f"Transaction is already {txn.status}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = POSSettleSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        from django.utils import timezone

        txn.status          = POSTransaction.Status.SETTLED
        txn.settlement_date = serializer.validated_data['settlement_date']
        txn.settled_by      = request.user
        txn.save(update_fields=[
            'status', 'settlement_date', 'settled_by', 'updated_at'
        ])

        return Response(POSTransactionSerializer(txn).data)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Receipts
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class ReceiptDetailView(generics.RetrieveAPIView):
    """
    GET /api/v1/finance/receipts/<id>/
    """
    serializer_class   = ReceiptSerializer
    permission_classes = [IsAuthenticated]
    queryset = Receipt.objects.select_related(
        'job', 'job__intake_by', 'cashier'
    ).prefetch_related('job__line_items__service')


class ReceiptSendWhatsAppView(APIView):
    """
    POST /api/v1/finance/receipts/<id>/send-whatsapp/
    Re-send or send receipt via WhatsApp.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            receipt = Receipt.objects.select_related(
                'job__branch'
            ).get(pk=pk)
        except Receipt.DoesNotExist:
            return Response(
                {'detail': 'Receipt not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        engine  = ReceiptEngine(receipt.job.branch)
        success = engine.send_whatsapp(receipt)

        if success:
            return Response({'detail': 'Receipt sent via WhatsApp.'})
        return Response(
            {'detail': 'WhatsApp delivery failed â€” check phone number.'},
            status=status.HTTP_400_BAD_REQUEST,
        )


class ReceiptThermalView(APIView):
    """
    GET /api/v1/finance/receipts/<id>/thermal/
    Returns the thermal-formatted receipt as plain text.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            receipt = Receipt.objects.select_related(
                'job__branch', 'cashier'
            ).get(pk=pk)
        except Receipt.DoesNotExist:
            return Response(
                {'detail': 'Receipt not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        engine = ReceiptEngine(receipt.job.branch)
        text   = engine.format_thermal(receipt)

        return Response({'text': text})

class ReceiptListView(generics.ListAPIView):
    """
    GET /api/v1/finance/receipts/
    Branch-scoped receipt list. Optional ?period=day|week|month filter.
    Paginated: 10 per page.
    """
    serializer_class   = ReceiptSerializer
    permission_classes = [IsAuthenticated]
    pagination_class   = StandardResultsPagination

    def get_queryset(self):
        from django.utils import timezone
        from apps.finance.models import Receipt

        branch = getattr(self.request.user, 'branch', None)
        if not branch:
            return Receipt.objects.none()

        qs = Receipt.objects.select_related(
            'job', 'job__intake_by', 'cashier', 'daily_sheet'
        ).prefetch_related(
            'job__line_items__service'
        ).filter(
            daily_sheet__branch=branch
        ).order_by('-created_at')

        period = self.request.query_params.get('period')
        now    = timezone.now()
        today  = now.date()

        if period == 'day':
            qs = qs.filter(created_at__date=today)
        elif period == 'week':
            # Monday â†’ today
            week_start = today - __import__('datetime').timedelta(days=today.weekday())
            qs = qs.filter(created_at__date__gte=week_start)
        elif period == 'month':
            qs = qs.filter(
                created_at__year=today.year,
                created_at__month=today.month,
            )

        return qs


class CashierReceiptListView(generics.ListAPIView):
    """
    GET /api/v1/finance/cashier/receipts/
    Returns receipts issued by the logged-in cashier.
    Ordered newest first. Optional ?date=YYYY-MM-DD filter.
    """
    serializer_class   = ReceiptSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs   = Receipt.objects.filter(
            cashier=user,
            is_void=False,
        ).select_related('job', 'daily_sheet').order_by('-created_at')

        date_param = self.request.query_params.get('date')
        if date_param:
            qs = qs.filter(created_at__date=date_param)

        return qs
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Credit Accounts
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class CreditAccountListView(generics.ListAPIView):
    """
    GET /api/v1/finance/credit/
    """
    serializer_class   = CreditAccountSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return CreditAccount.objects.select_related(
            'customer', 'nominated_by', 'approved_by'
        )


class CreditAccountDetailView(generics.RetrieveAPIView):
    """
    GET /api/v1/finance/credit/<id>/
    """
    serializer_class   = CreditAccountSerializer
    permission_classes = [IsAuthenticated]
    queryset           = CreditAccount.objects.select_related(
        'customer', 'recommended_by', 'approved_by'
    )


class CreditAccountCreateView(APIView):
    """
    POST /api/v1/finance/credit/
    BM recommends a credit account.
    Belt Manager approves via separate endpoint.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CreditAccountCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        from apps.customers.models import CustomerProfile

        try:
            customer = CustomerProfile.objects.get(
                pk=serializer.validated_data['customer_id']
            )
        except CustomerProfile.DoesNotExist:
            return Response(
                {'detail': 'Customer not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if hasattr(customer, 'credit_account'):
            return Response(
                {'detail': 'Customer already has a credit account.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        account = CreditAccount.objects.create(
            customer          = customer,
            account_type      = serializer.validated_data['account_type'],
            credit_limit      = serializer.validated_data['credit_limit'],
            payment_terms     = serializer.validated_data.get('payment_terms', 30),
            organisation_name = serializer.validated_data.get('organisation_name', ''),
            contact_person    = serializer.validated_data.get('contact_person', ''),
            contact_phone     = serializer.validated_data.get('contact_phone', ''),
            notes             = serializer.validated_data.get('notes', ''),
            recommended_by    = request.user,
            approved_by       = request.user,  # placeholder â€” overwritten on approval
            status            = CreditAccount.Status.SUSPENDED,  # inactive until approved
        )

        return Response(
            CreditAccountSerializer(account).data,
            status=status.HTTP_201_CREATED,
        )


class CreditAccountApproveView(APIView):
    """
    POST /api/v1/finance/credit/<id>/approve/
    Belt Manager approves or rejects a recommended credit account.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            account = CreditAccount.objects.get(pk=pk)
        except CreditAccount.DoesNotExist:
            return Response(
                {'detail': 'Credit account not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = CreditAccountApproveSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        from django.utils import timezone

        if serializer.validated_data['approved']:
            account.status      = CreditAccount.Status.ACTIVE
            account.approved_by = request.user
            account.approved_at = timezone.now()
            account.notes       = serializer.validated_data.get('notes', account.notes)
        else:
            account.status = CreditAccount.Status.CLOSED
            account.notes  = serializer.validated_data.get('notes', account.notes)

        account.save()

        return Response(CreditAccountSerializer(account).data)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Credit Settlements
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class CreditSettlementView(APIView):
    """
    POST /api/v1/finance/credit/<id>/settle/
    Record a credit settlement payment against an account.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            account = CreditAccount.objects.select_related('customer').get(pk=pk)
        except CreditAccount.DoesNotExist:
            return Response(
                {'detail': 'Credit account not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = CreditSettlementSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        user  = request.user
        sheet = self._get_today_sheet(user)
        if not sheet:
            return Response(
                {'detail': 'No open sheet for today â€” cannot process settlement.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            engine  = CreditEngine(account)
            payment = engine.settle(
                amount            = serializer.validated_data['amount'],
                payment_method    = serializer.validated_data['payment_method'],
                actor             = user,
                daily_sheet       = sheet,
                momo_reference    = serializer.validated_data.get('momo_reference', ''),
                pos_approval_code = serializer.validated_data.get('pos_approval_code', ''),
                notes             = serializer.validated_data.get('notes', ''),
            )
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            CreditPaymentSerializer(payment).data,
            status=status.HTTP_201_CREATED,
        )

    def _get_today_sheet(self, user):
        from django.utils import timezone
        try:
            return DailySalesSheet.objects.get(
                branch=user.branch,
                date=timezone.localdate(),
                status=DailySalesSheet.Status.OPEN,
            )
        except DailySalesSheet.DoesNotExist:
            return None


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Branch Transfer Credits
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class BranchTransferCreditListView(generics.ListAPIView):
    """
    GET /api/v1/finance/transfers/
    Belt Manager sees all pending transfer credits for reconciliation.
    """
    serializer_class   = BranchTransferCreditSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs           = BranchTransferCredit.objects.select_related(
            'job', 'origin_branch', 'destination_branch', 'reconciled_by'
        )
        status_param = self.request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param)
        return qs


class BranchTransferCreditReconcileView(APIView):
    """
    POST /api/v1/finance/transfers/<id>/reconcile/
    Belt Manager marks a transfer credit as reconciled.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            transfer = BranchTransferCredit.objects.get(pk=pk)
        except BranchTransferCredit.DoesNotExist:
            return Response(
                {'detail': 'Transfer credit not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if transfer.status == BranchTransferCredit.Status.RECONCILED:
            return Response(
                {'detail': 'Already reconciled.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from django.utils import timezone

        transfer.status               = BranchTransferCredit.Status.RECONCILED
        transfer.reconciled_by        = request.user
        transfer.reconciled_at        = timezone.now()
        transfer.reconciliation_notes = request.data.get('notes', '')
        transfer.save(update_fields=[
            'status', 'reconciled_by',
            'reconciled_at', 'reconciliation_notes', 'updated_at',
        ])

        return Response(BranchTransferCreditSerializer(transfer).data)

class DailySalesSheetPDFView(APIView):
    """
    GET /api/v1/finance/sheets/<pk>/pdf/
    Generates and serves the day sheet as a read-only PDF.
    Only accessible by branch manager of that branch.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            sheet = DailySalesSheet.objects.get(pk=pk)
        except DailySalesSheet.DoesNotExist:
            return Response({'detail': 'Sheet not found.'}, status=404)

        if request.user.branch != sheet.branch:
            return Response({'detail': 'Access denied.'}, status=403)

        if sheet.status not in (DailySalesSheet.Status.CLOSED, DailySalesSheet.Status.AUTO_CLOSED):
            return Response(
                {'detail': 'Sheet must be closed before downloading.'},
                status=400
            )

        # â”€â”€ Download limit: 2 per BM, then view-only â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        from apps.finance.models import SheetDownloadLog
        user_role = getattr(getattr(request.user, 'role', None), 'name', '')
        hq_roles  = {'SUPER_ADMIN', 'REGIONAL_MANAGER', 'BELT_MANAGER',
                    'NATIONAL_FINANCE_HEAD', 'NATIONAL_FINANCE_DEPUTY'}
        is_hq     = user_role in hq_roles

        download_count = SheetDownloadLog.objects.filter(
            sheet=sheet, downloaded_by=request.user
        ).count()

        view_only = (not is_hq) and (download_count >= 2)

        # â”€â”€ Generate PDF if not cached â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        import os
        from django.conf import settings
        from django.core.management import call_command

        media_root  = getattr(settings, 'MEDIA_ROOT', 'media')
        sheets_dir  = os.path.join(media_root, 'sheets')
        os.makedirs(sheets_dir, exist_ok=True)
        output_path = os.path.join(sheets_dir, f"sheet_{sheet.pk}_{sheet.date}.pdf")

        if not os.path.exists(output_path):
            call_command('generate_sheet_pdf', sheet_id=sheet.pk, output=output_path)

        # â”€â”€ Log download (only if not view-only) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if not view_only:
            ip = (request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip()
                or request.META.get('REMOTE_ADDR'))
            SheetDownloadLog.objects.create(
                sheet=sheet, downloaded_by=request.user, ip_address=ip or None
            )

        # â”€â”€ Serve â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        from django.http import FileResponse
        disposition = 'inline' if view_only else 'attachment'
        response = FileResponse(
            open(output_path, 'rb'),
            content_type='application/pdf',
        )
        response['Content-Disposition'] = (
            f'{disposition}; filename="sheet_{sheet.branch.code}_{sheet.date}.pdf"'
        )
        if view_only:
            response['X-Download-Limit-Reached'] = 'true'
        return response

class BranchLockStatusView(APIView):
    """
    GET /api/v1/finance/lock-status/
    Returns current branch lock state â€” can jobs be created?
    Frontend uses this to show/hide New Job button.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if not hasattr(user, 'branch') or not user.branch:
            return Response(
                {'detail': 'User has no branch assigned.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from apps.finance.models import CashierFloat, DailySalesSheet
        from django.utils import timezone

        status_data = SheetEngine(user.branch).get_branch_lock_status()

        # Check for active float dispute â€” hard blocks BM portal
        today = timezone.localdate()
        float_dispute_active = CashierFloat.objects.filter(
            daily_sheet__branch  = user.branch,
            daily_sheet__date    = today,
            physical_confirm_disputed = True,
            morning_acknowledged = False,
        ).select_related('cashier').first()

        if float_dispute_active:
            status_data['float_dispute_active']   = True
            status_data['dispute_cashier_name']   = float_dispute_active.cashier.full_name
            status_data['dispute_float_amount']   = str(float_dispute_active.opening_float)
            status_data['dispute_float_id']       = float_dispute_active.pk
        else:
            status_data['float_dispute_active'] = False

        return Response(status_data)

class EODSummaryView(APIView):
    """
    GET /api/v1/finance/sheets/<pk>/eod-summary/
    Returns a comprehensive end-of-day summary for the pre-close checklist.
    Only accessible by the branch manager of the sheet's branch.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        from apps.finance.services.eod_service import EODService

        try:
            sheet = DailySalesSheet.objects.select_related(
                'branch', 'opened_by', 'closed_by'
            ).get(pk=pk)
        except DailySalesSheet.DoesNotExist:
            return Response(
                {'detail': 'Sheet not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if sheet.branch != getattr(request.user, 'branch', None):
            return Response(
                {'detail': 'Access denied.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        summary = EODService.get_summary(sheet, sheet.branch)
        return Response(summary)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Invoices
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class InvoiceListView(generics.ListAPIView):
    """
    GET /api/v1/finance/invoices/
    Returns invoices for the requesting user's branch.
    Optional ?period=day|week|month, ?type=, ?status= filters.
    Paginated: 10 per page.
    """
    serializer_class   = InvoiceSerializer
    permission_classes = [IsAuthenticated]
    pagination_class   = StandardResultsPagination

    def get_queryset(self):
        from django.utils import timezone
        user = self.request.user
        qs   = Invoice.objects.select_related(
            'branch', 'job', 'generated_by'
        ).prefetch_related('line_items__service')

        if hasattr(user, 'branch') and user.branch:
            qs = qs.filter(branch=user.branch)

        invoice_type = self.request.query_params.get('type')
        status_param = self.request.query_params.get('status')
        if invoice_type:
            qs = qs.filter(invoice_type=invoice_type)
        if status_param:
            qs = qs.filter(status=status_param)

        period = self.request.query_params.get('period')
        today  = timezone.now().date()
        if period == 'day':
            qs = qs.filter(issue_date=today)
        elif period == 'week':
            week_start = today - __import__('datetime').timedelta(days=today.weekday())
            qs = qs.filter(issue_date__gte=week_start)
        elif period == 'month':
            qs = qs.filter(issue_date__year=today.year, issue_date__month=today.month)

        return qs.order_by('-issue_date', '-id')


class InvoiceDetailView(generics.RetrieveAPIView):
    """
    GET /api/v1/finance/invoices/<id>/
    """
    serializer_class   = InvoiceSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Invoice.objects.select_related(
            'branch', 'job', 'generated_by'
        ).prefetch_related('line_items__service')


class InvoiceCreateView(APIView):
    """
    POST /api/v1/finance/invoices/
    Create a job-linked or standalone invoice.
    Generates PDF and delivers via selected channel.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from apps.finance.services.invoice_service import InvoiceService

        serializer = InvoiceCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        branch = getattr(request.user, 'branch', None)
        if not branch:
            return Response(
                {'detail': 'No branch assigned.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        invoice, errors = InvoiceService.create(
            data   = serializer.validated_data,
            user   = request.user,
            branch = branch,
        )
        if errors:
            return Response({'detail': errors[0]}, status=status.HTTP_400_BAD_REQUEST)

        return Response(InvoiceSerializer(invoice).data, status=status.HTTP_201_CREATED)

class InvoiceSendView(APIView):
    """
    POST /api/v1/finance/invoices/<id>/send/
    Re-send an existing invoice via its delivery channel.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            invoice = Invoice.objects.get(pk=pk)
        except Invoice.DoesNotExist:
            return Response(
                {'detail': 'Invoice not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        _deliver_invoice(invoice)
        return Response({'detail': 'Invoice sent.'})


class InvoicePDFView(APIView):
    """
    GET /api/v1/finance/invoices/<id>/pdf/
    Download the invoice PDF.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            invoice = Invoice.objects.get(pk=pk)
        except Invoice.DoesNotExist:
            return Response({'detail': 'Invoice not found.'}, status=404)

        # Regenerate if missing
        if not invoice.pdf_path:
            try:
                _generate_invoice_pdf(invoice)
            except Exception as e:
                return Response(
                    {'detail': f'PDF generation failed: {e}'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        import os
        if not os.path.exists(invoice.pdf_path):
            try:
                _generate_invoice_pdf(invoice)
            except Exception as e:
                return Response(
                    {'detail': f'PDF generation failed: {e}'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        from django.http import FileResponse
        response = FileResponse(
            open(invoice.pdf_path, 'rb'),
            content_type='application/pdf',
        )
        response['Content-Disposition'] = (
            f'attachment; filename="{invoice.invoice_number}.pdf"'
        )
        return response


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Invoice helpers
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _generate_invoice_pdf(invoice):
    """Generate a PDF for the invoice and save path to invoice.pdf_path."""
    import os
    from django.conf import settings

    media_root   = getattr(settings, 'MEDIA_ROOT', 'media')
    invoices_dir = os.path.join(media_root, 'invoices')
    os.makedirs(invoices_dir, exist_ok=True)
    output_path  = os.path.join(invoices_dir, f"{invoice.invoice_number}.pdf")

    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT

    doc    = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=20*mm, leftMargin=20*mm,
        topMargin=20*mm,   bottomMargin=20*mm,
    )
    W = A4[0] - 40*mm

    # ── Styles ────────────────────────────────────────────────────────────
    h1 = ParagraphStyle('h1', fontSize=20, fontName='Helvetica-Bold',
                         textColor=colors.HexColor('#111111'))
    sm = ParagraphStyle('sm', fontSize=9, fontName='Helvetica',
                         textColor=colors.HexColor('#666666'))
    sm_bold = ParagraphStyle('smb', fontSize=9, fontName='Helvetica-Bold',
                              textColor=colors.HexColor('#111111'))
    sm_dark = ParagraphStyle('smd', fontSize=9, fontName='Helvetica',
                              textColor=colors.HexColor('#444444'))
    right = ParagraphStyle('right', fontSize=9, fontName='Helvetica',
                            alignment=TA_RIGHT, textColor=colors.HexColor('#666666'))
    right_bold = ParagraphStyle('rightb', fontSize=11, fontName='Helvetica-Bold',
                                 alignment=TA_RIGHT, textColor=colors.HexColor('#111111'))
    center_sm = ParagraphStyle('csm', fontSize=9, fontName='Helvetica',
                                alignment=TA_CENTER, textColor=colors.HexColor('#444444'))
    right_sm = ParagraphStyle('rsm', fontSize=9, fontName='Helvetica',
                               alignment=TA_RIGHT, textColor=colors.HexColor('#444444'))
    right_sm_bold = ParagraphStyle('rsmb', fontSize=9, fontName='Helvetica-Bold',
                                    alignment=TA_RIGHT, textColor=colors.HexColor('#111111'))

    def fmt(n):
        return f"GHS {float(n or 0):,.2f}"

    story = []
    branch = invoice.branch

    # ── Header: company name + invoice type badge ─────────────────────────
    type_color = '#1a4fd6' if invoice.invoice_type == 'PROFORMA' else '#1a7a4a'
    header_data = [[
        Paragraph('Farhat Printing Press', h1),
        Paragraph(
            f"<b>{invoice.invoice_type} INVOICE</b>",
            ParagraphStyle('inv', fontSize=14, fontName='Helvetica-Bold',
                           alignment=TA_RIGHT,
                           textColor=colors.HexColor(type_color))
        ),
    ]]
    header_table = Table(header_data, colWidths=[W*0.6, W*0.4])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
    ]))
    story.append(header_table)

    # Branch info block
    branch_info_parts = [branch.name]
    if branch.phone or branch.whatsapp_number:
        branch_info_parts.append(branch.phone or branch.whatsapp_number)
    if branch.email:
        branch_info_parts.append(branch.email)
    if branch.address:
        branch_info_parts.append(branch.address)

    for part in branch_info_parts:
        story.append(Paragraph(part, sm))

    story.append(Spacer(1, 6*mm))
    story.append(HRFlowable(width=W, thickness=1, color=colors.HexColor('#eeeeee')))
    story.append(Spacer(1, 6*mm))

    # ── Bill To + Invoice meta ────────────────────────────────────────────
    issued = invoice.issue_date.strftime('%d %b %Y') if invoice.issue_date else '—'
    due    = invoice.due_date.strftime('%d %b %Y')   if invoice.due_date   else '—'

    # Company first (bold), then rep name, phone, email
    bill_paragraphs = [
        Paragraph('BILL TO', ParagraphStyle('lbl', fontSize=8,
            fontName='Helvetica-Bold',
            textColor=colors.HexColor('#aaaaaa'),
            spaceAfter=3)),
    ]
    # Primary display name — company if available, else personal name
    primary   = invoice.bill_to_company or invoice.bill_to_name
    secondary = invoice.bill_to_name if invoice.bill_to_company else None
    bill_paragraphs.append(Paragraph(primary, sm_bold))
    if secondary:
        bill_paragraphs.append(Paragraph(secondary, sm_dark))
    if invoice.bill_to_phone:
        bill_paragraphs.append(Paragraph(invoice.bill_to_phone, sm))
    if invoice.bill_to_email:
        bill_paragraphs.append(Paragraph(invoice.bill_to_email, sm))

    meta_data = [[
        bill_paragraphs,
        [
            Paragraph('INVOICE NO', ParagraphStyle('lbl', fontSize=8,
                fontName='Helvetica-Bold',
                textColor=colors.HexColor('#aaaaaa'),
                alignment=TA_RIGHT, spaceAfter=3)),
            Paragraph(invoice.invoice_number, right_bold),
            Spacer(1, 4),
            Paragraph('DATE ISSUED', ParagraphStyle('lbl2', fontSize=8,
                fontName='Helvetica-Bold',
                textColor=colors.HexColor('#aaaaaa'),
                alignment=TA_RIGHT, spaceAfter=3)),
            Paragraph(issued, right),
            Spacer(1, 4),
            Paragraph('DUE DATE', ParagraphStyle('lbl3', fontSize=8,
                fontName='Helvetica-Bold',
                textColor=colors.HexColor('#aaaaaa'),
                alignment=TA_RIGHT, spaceAfter=3)),
            Paragraph(due, right),
        ],
    ]]
    meta_table = Table(meta_data, colWidths=[W*0.5, W*0.5])
    meta_table.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'TOP')]))
    story.append(meta_table)
    story.append(Spacer(1, 8*mm))

    # Job ref
    if invoice.job:
        story.append(Paragraph(f"Job Reference: <b>{invoice.job.job_number}</b>", sm))
        story.append(Spacer(1, 4*mm))

    # ── Line items: # | DESCRIPTION | QTY | UNIT PRICE | AMOUNT ─────────
    th_style = ParagraphStyle('th', fontSize=8, fontName='Helvetica-Bold',
                               textColor=colors.HexColor('#aaaaaa'))
    th_center = ParagraphStyle('thc', fontSize=8, fontName='Helvetica-Bold',
                                textColor=colors.HexColor('#aaaaaa'), alignment=TA_CENTER)
    th_right  = ParagraphStyle('thr', fontSize=8, fontName='Helvetica-Bold',
                                textColor=colors.HexColor('#aaaaaa'), alignment=TA_RIGHT)

    table_data = [[
        Paragraph('#',          th_style),
        Paragraph('DESCRIPTION', th_style),
        Paragraph('QTY',        th_center),
        Paragraph('UNIT PRICE', th_right),
        Paragraph('AMOUNT',     th_right),
    ]]

    for idx, li in enumerate(invoice.line_items.all().order_by('position'), start=1):
        qty        = (li.quantity or 1) * (li.pages or 1)
        line_total = float(li.line_total or 0)
        unit_price = line_total / qty if qty > 0 else 0

        sets_label = li.sets or li.quantity or 1
        pages_label = li.pages or 1
        color_label = 'Colour' if li.is_color else 'B&W'
        detail = f"{sets_label} set{'s' if sets_label != 1 else ''} × {pages_label}pp · {color_label}"

        table_data.append([
            Paragraph(str(idx), sm_dark),
            [
                Paragraph(li.label or li.service.name if li.service else li.label, sm_bold),
                Paragraph(detail, sm),
            ],
            Paragraph(str(qty), center_sm),
            Paragraph(fmt(unit_price), right_sm),
            Paragraph(fmt(li.line_total), right_sm_bold),
        ])

    col_w = [W*0.05, W*0.45, W*0.1, W*0.2, W*0.2]
    items_table = Table(table_data, colWidths=col_w, repeatRows=1)
    items_table.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,0),  colors.HexColor('#f7f7f7')),
        ('ROWBACKGROUNDS',(0,1), (-1,-1), [colors.white, colors.HexColor('#fafafa')]),
        ('GRID',          (0,0), (-1,-1), 0.5, colors.HexColor('#eeeeee')),
        ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING',    (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('LEFTPADDING',   (0,0), (-1,-1), 8),
        ('RIGHTPADDING',  (0,0), (-1,-1), 8),
    ]))
    story.append(items_table)
    story.append(Spacer(1, 6*mm))

    # ── Totals ────────────────────────────────────────────────────────────
    totals_data = [[
        Paragraph('Subtotal', sm),
        Paragraph(fmt(invoice.subtotal), right),
    ]]
    if invoice.vat_rate:
        totals_data.append([
            Paragraph(f'VAT ({invoice.vat_rate}%)', sm),
            Paragraph(fmt(invoice.vat_amount), right),
        ])
    totals_data.append([
        Paragraph('<b>Total</b>', ParagraphStyle('tb', fontSize=11,
            fontName='Helvetica-Bold', textColor=colors.HexColor('#111111'))),
        Paragraph(f'<b>{fmt(invoice.total)}</b>',
            ParagraphStyle('trb', fontSize=11, fontName='Helvetica-Bold',
                           alignment=TA_RIGHT, textColor=colors.HexColor('#111111'))),
    ])
    totals_table = Table(totals_data, colWidths=[W*0.75, W*0.25])
    totals_table.setStyle(TableStyle([
        ('ALIGN',         (1,0), (1,-1), 'RIGHT'),
        ('LINEABOVE',     (0,-1), (-1,-1), 1, colors.HexColor('#eeeeee')),
        ('TOPPADDING',    (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(totals_table)

    # ── BM note ───────────────────────────────────────────────────────────
    if invoice.bm_note:
        story.append(Spacer(1, 6*mm))
        story.append(HRFlowable(width=W, thickness=0.5,
                                 color=colors.HexColor('#eeeeee')))
        story.append(Spacer(1, 4*mm))
        story.append(Paragraph(invoice.bm_note, sm))

    # ── Footer ────────────────────────────────────────────────────────────
    story.append(Spacer(1, 10*mm))
    story.append(HRFlowable(width=W, thickness=0.5,
                             color=colors.HexColor('#eeeeee')))
    story.append(Spacer(1, 3*mm))
    story.append(Paragraph(
        'Thank you for your business — Farhat Printing Press',
        ParagraphStyle('ft', fontSize=8, fontName='Helvetica',
                       textColor=colors.HexColor('#aaaaaa'),
                       alignment=TA_CENTER)
    ))

    doc.build(story)
    invoice.pdf_path = output_path
    invoice.save(update_fields=['pdf_path', 'updated_at'])

