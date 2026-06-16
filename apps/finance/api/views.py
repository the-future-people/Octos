import calendar
import logging
import os
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.mail import EmailMessage
from django.core.management import call_command
from django.db.models import Sum, Q, Count
from django.db.models.functions import (
    TruncYear, TruncMonth, TruncWeek, TruncDay,
    ExtractYear, ExtractMonth, ExtractWeek, ExtractDay
)
from django.http import FileResponse, HttpResponse
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
    HRFlowable, PageBreak, BaseDocTemplate, Frame, PageTemplate
)
from reportlab.platypus.flowables import Flowable
from rest_framework import generics, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import CustomUser
from apps.analytics.models import MonthlyCloseSummary
from apps.core.finance_scope import get_finance_scope, REGIONAL_ROLES, NATIONAL_ROLES
from apps.customers.models import CustomerProfile
from apps.finance.credit_engine import CreditEngine
from apps.finance.float_engine import FloatEngine
from apps.finance.models import (
    DailySalesSheet, CashierFloat, PettyCash, POSTransaction,
    Receipt, CreditAccount, CreditPayment, BranchTransferCredit,
    Invoice, InvoiceLineItem, WeeklyReport, MonthlyClose, SheetDownloadLog
)
from apps.finance.monthly_close_engine import MonthlyCloseEngine
from apps.finance.receipt_engine import ReceiptEngine
from apps.finance.services.eod_service import EODService
from apps.finance.services.invoice_service import InvoiceService
from apps.finance.services.sheet_summary_service import SheetSummaryService
from apps.finance.services.weekly_report_service import WeeklyReportService
from apps.finance.sheet_engine import SheetEngine
from apps.hr.shift_engine import ShiftEngine as HRShiftEngine
from apps.jobs.models import Job
from apps.notifications.services import notify

from .serializers import (
    DailySalesSheetListSerializer, DailySalesSheetDetailSerializer,
    DailySalesSheetNotesSerializer, CashierFloatSerializer,
    CashierFloatSetSerializer, CashierFloatCloseSerializer,
    PettyCashSerializer, PettyCashCreateSerializer,
    POSTransactionSerializer, POSSettleSerializer, ReceiptSerializer,
    CreditAccountSerializer, CreditAccountCreateSerializer,
    CreditAccountApproveSerializer, CreditPaymentSerializer,
    CreditSettlementSerializer, BranchTransferCreditSerializer,
    CashierSignOffSerializer, InvoiceSerializer, InvoiceCreateSerializer,
    WeeklyReportListSerializer, WeeklyReportDetailSerializer,
    WeeklyReportNotesSerializer,
)

logger = logging.getLogger(__name__)

FINANCE_ROLES = (
    'FINANCE', 'NATIONAL_FINANCE_HEAD', 'NATIONAL_FINANCE_DEPUTY',
    'BELT_FINANCE_OFFICER', 'BELT_FINANCE_DEPUTY',
    'REGIONAL_FINANCE_OFFICER', 'REGIONAL_FINANCE_DEPUTY', 'SUPER_ADMIN',
)

# ============================================================================
# Pagination
# ============================================================================

class StandardResultsPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100


# ============================================================================
# Daily Sales Sheet
# ============================================================================

class DailySalesSheetListView(generics.ListAPIView):
    """
    GET /api/v1/finance/sheets/
    Returns sheets for the requesting user's branch.
    Belt/Region managers see all sheets across their scope.
    """
    serializer_class = DailySalesSheetListSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        user = self.request.user
        qs = DailySalesSheet.objects.select_related(
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
            now = timezone.localdate()
            since = {
                'day': now,
                'week': now - timedelta(days=now.weekday()),
                'month': now.replace(day=1),
                'year': now.replace(month=1, day=1),
            }.get(period)
            if since:
                qs = qs.filter(date__gte=since)

        return qs


class DailySalesSheetDetailView(generics.RetrieveAPIView):
    """
    GET /api/v1/finance/sheets/<id>/
    Full sheet detail including floats and petty cash.
    """
    serializer_class = DailySalesSheetDetailSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs = DailySalesSheet.objects.select_related(
            'branch', 'opened_by', 'closed_by'
        ).prefetch_related('cashier_floats', 'petty_cash_entries')

        if hasattr(user, 'branch') and user.branch:
            qs = qs.filter(branch=user.branch)
        return qs


class DailySalesSheetTodayView(APIView):
    """
    GET /api/v1/finance/sheets/today/
    Returns today's sheet for the user's branch.
    Creates one if it doesn't exist (fallback open).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if not hasattr(user, 'branch') or not user.branch:
            return Response(
                {'detail': 'User has no branch assigned.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        sheet, _ = SheetEngine(user.branch).get_or_open_today(opened_by=user)

        if sheet is None:
            return Response(
                {'detail': 'No sheet today - branch may be closed (Sunday).'},
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
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if not hasattr(user, 'branch') or not user.branch:
            return Response(
                {'detail': 'User has no branch assigned.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        sheet, _ = SheetEngine(user.branch).get_or_open_today(opened_by=user)

        if sheet is None:
            return Response(
                {'detail': 'No sheet today - branch may be closed (Sunday).'},
                status=status.HTTP_404_NOT_FOUND,
            )

        summary = SheetSummaryService.get_summary(sheet, sheet.branch)
        return Response(summary)


class DailySalesSheetSummaryView(APIView):
    """
    GET /api/v1/finance/sheets/<pk>/summary/
    Unified day sheet summary for the BM portal.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            sheet = DailySalesSheet.objects.select_related(
                'branch', 'opened_by', 'closed_by'
            ).get(pk=pk)
        except DailySalesSheet.DoesNotExist:
            return Response(
                {'detail': 'Sheet not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

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
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class DailySalesSheetCloseView(APIView):
    """
    POST /api/v1/finance/sheets/<id>/close/
    BM closes the daily sheet.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            sheet = DailySalesSheet.objects.select_related('branch').get(
                pk=pk,
                branch=request.user.branch,
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

        # Gate 1: All cashiers signed off
        signoff_gate = FloatEngine.validate_signoff_gate(sheet)
        if not signoff_gate['passed']:
            errors.extend(signoff_gate['errors'])

        # Gate 2: No pending instant payments
        pending = Job.objects.filter(
            daily_sheet=sheet,
            status=Job.PENDING_PAYMENT,
            job_type='INSTANT',
        ).count()
        if pending:
            errors.append(
                f"{pending} instant job(s) still pending payment. "
                f"Resolve before closing."
            )

        # Stage tomorrow's floats BEFORE Gate 3
        floats_data = request.data.get('floats', [])
        tomorrow = sheet.date + timedelta(days=1)
        if tomorrow.weekday() == 6:
            tomorrow = tomorrow + timedelta(days=1)

        for f in floats_data:
            try:
                cashier = CustomUser.objects.get(
                    pk=f['cashier_id'],
                    branch=sheet.branch,
                )
                FloatEngine.stage_float(
                    cashier=cashier,
                    amount=Decimal(str(f['opening_float'])),
                    set_by=request.user,
                    target_date=tomorrow,
                    branch=sheet.branch,
                )
            except Exception as e:
                logger.warning(f"Failed to stage float: {e}")

        # Gate 3: Tomorrow's float set
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

        try:
            engine = SheetEngine(sheet.branch)
            closed = engine.close_sheet(
                sheet=sheet,
                closed_by=request.user,
                auto=False,
            )
        except ValueError as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(DailySalesSheetListSerializer(closed).data)


# ============================================================================
# Cashier Float
# ============================================================================

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
                'opening_float': serializer.validated_data['opening_float'],
                'float_set_by': request.user,
                'float_set_at': timezone.now(),
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

        float_record.closing_cash = serializer.validated_data['closing_cash']
        float_record.variance_notes = serializer.validated_data.get('variance_notes', '')
        float_record.compute_variance()
        float_record.save(update_fields=[
            'closing_cash', 'variance_notes', 'variance', 'updated_at'
        ])

        return Response(CashierFloatSerializer(float_record).data)


# ============================================================================
# Cashier Sign-Off
# ============================================================================

class CashierSignOffView(APIView):
    """
    POST /api/v1/finance/floats/<id>/sign-off/
    Cashier submits closing cash, variance notes, shift notes.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
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

        is_handover = request.data.get('is_handover', False)
        is_overtime = request.data.get('is_overtime', False)
        is_cover = request.data.get('is_cover', False)

        # Mid-day handover
        if is_handover:
            handover_amount = request.data.get('handover_amount', 0)
            breakdown = request.data.get('breakdown', {})
            shift_notes = request.data.get('shift_notes', '')

            result = FloatEngine.mid_day_handover(
                float_record=float_record,
                handover_amount=handover_amount,
                breakdown=breakdown,
                signed_off_by=request.user,
                shift_notes=shift_notes,
            )

            if not result['ok']:
                return Response(
                    {'detail': result['error']},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            return Response({
                'detail': 'Handover recorded. Next cashier float staged.',
                'is_handover': True,
                'handover_amount': str(result['float'].handover_float),
                'next_float_id': result['next_staged'].pk,
            })

        # Overtime extension
        if is_overtime or is_cover:
            overtime_until = request.data.get('overtime_until')
            overtime_reason = request.data.get('overtime_reason', '')
            cover_until = request.data.get('cover_until')

            float_record.is_overtime = is_overtime
            float_record.overtime_reason = overtime_reason
            float_record.overtime_until = overtime_until
            float_record.is_cover = is_cover
            float_record.cover_until = cover_until

            if request.data.get('covering_for_id'):
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
                'detail': 'Shift extended.',
                'is_overtime': float_record.is_overtime,
                'overtime_until': float_record.overtime_until,
                'is_cover': float_record.is_cover,
                'cover_until': float_record.cover_until,
            })

        # EOD sign-off
        closing_cash = request.data.get('closing_cash', 0)
        breakdown = request.data.get('breakdown', {})
        variance_notes = request.data.get('variance_notes', '')
        shift_notes = request.data.get('shift_notes', '')

        result = FloatEngine.sign_off(
            float_record=float_record,
            closing_cash=closing_cash,
            breakdown=breakdown,
            variance_notes=variance_notes,
            shift_notes=shift_notes,
            signed_off_by=request.user,
            is_overtime=False,
        )

        if not result['ok']:
            return Response(
                {'detail': result['error']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(CashierFloatSerializer(result['float']).data)


def _compute_expected_cash(float_record):
    """Expected cash = opening float + all cash payments collected by this cashier today."""
    cash_collected = Receipt.objects.filter(
        cashier=float_record.cashier,
        daily_sheet=float_record.daily_sheet,
        payment_method='CASH',
        is_void=False,
    ).aggregate(t=Sum('amount_paid'))['t'] or Decimal('0.00')

    return float_record.opening_float + cash_collected


class CashierShiftStatusView(APIView):
    """
    GET /api/v1/finance/cashier/shift-status/
    Returns current shift state for the logged-in cashier.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        branch = getattr(user, 'branch', None)

        if not branch:
            return Response(
                {'detail': 'No branch assigned.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        today = timezone.localdate()
        now = timezone.now()

        float_status = FloatEngine.get_float_status(
            cashier=user,
            branch=branch,
            date=today,
        )

        # Resolve sheet_number
        sheet_number = ''
        if float_status.get('sheet_id'):
            try:
                sheet_number = DailySalesSheet.objects.filter(
                    pk=float_status['sheet_id']
                ).values_list('sheet_number', flat=True).first() or ''
            except Exception:
                pass

        # Signed off - return immediately
        if float_status['float_status'] == 'SIGNED_OFF':
            try:
                float_record = CashierFloat.objects.get(pk=float_status['float_id'])
                expected_cash = str(float_record.expected_cash)
            except Exception:
                expected_cash = '0'

            return Response({
                'has_shift': True,
                'float_status': 'SIGNED_OFF',
                'float_id': float_status['float_id'],
                'sheet_id': float_status['sheet_id'],
                'sheet_number': sheet_number,
                'opening_float': float_status['opening_float'],
                'opening_breakdown': float_status['opening_breakdown'],
                'expected_cash': expected_cash,
                'shift_end': None,
                'minutes_remaining': 0,
                'should_prompt': False,
                'should_lock': True,
                'is_signed_off': True,
                'is_overtime': False,
                'overtime_until': None,
                'is_cover': False,
                'cover_until': None,
            })

        # No float - return immediately
        if float_status['float_status'] == 'NO_FLOAT':
            return Response({
                'has_shift': False,
                'float_status': 'NO_FLOAT',
                'float_id': None,
                'sheet_id': None,
                'sheet_number': '',
                'opening_float': None,
                'opening_breakdown': None,
                'shift_end': None,
                'minutes_remaining': None,
                'should_prompt': False,
                'should_lock': False,
                'is_signed_off': False,
                'is_overtime': False,
                'overtime_until': None,
                'is_cover': False,
                'cover_until': None,
            })

        # Pending acknowledgement
        if float_status['float_status'] == 'PENDING_ACK':
            return Response({
                'has_shift': True,
                'float_status': 'PENDING_ACK',
                'float_id': float_status['float_id'],
                'sheet_id': float_status['sheet_id'],
                'sheet_number': sheet_number,
                'opening_float': float_status['opening_float'],
                'opening_breakdown': float_status['opening_breakdown'],
                'shift_end': None,
                'minutes_remaining': None,
                'should_prompt': False,
                'should_lock': False,
                'is_signed_off': False,
                'is_overtime': False,
                'overtime_until': None,
                'is_cover': False,
                'cover_until': None,
            })

        # Active shift - compute timing
        float_record = None
        if float_status['float_id']:
            try:
                float_record = CashierFloat.objects.get(pk=float_status['float_id'])
            except CashierFloat.DoesNotExist:
                pass

        # Overtime active
        if (float_record and float_record.is_overtime and float_record.overtime_until):
            delta = float_record.overtime_until - now
            mins_remaining = max(0, int(delta.total_seconds() / 60))
            return Response({
                'has_shift': True,
                'float_status': 'ACTIVE',
                'float_id': float_status['float_id'],
                'sheet_id': float_status['sheet_id'],
                'opening_float': float_status['opening_float'],
                'opening_breakdown': float_status['opening_breakdown'],
                'sheet_number': sheet_number,
                'shift_end': float_record.overtime_until.time(),
                'minutes_remaining': mins_remaining,
                'should_prompt': mins_remaining <= 60,
                'should_lock': mins_remaining <= 0,
                'is_signed_off': False,
                'is_overtime': True,
                'overtime_until': float_record.overtime_until,
                'is_cover': float_record.is_cover,
                'cover_until': float_record.cover_until,
            })

        # Normal active shift - get role schedule
        cash_schedule = HRShiftEngine(branch).get_role_schedule('CASHIER', target_date=today)
        signoff_dt = timezone.datetime.fromisoformat(cash_schedule['signoff_at'])
        delta = signoff_dt - now
        mins_remaining = max(0, int(delta.total_seconds() / 60))
        shift_end = timezone.datetime.fromisoformat(cash_schedule['shift_end']).time()

        float_status_val = float_status['float_status']
        if mins_remaining <= 0 and float_status_val == 'ACTIVE':
            float_status_val = 'PENDING_SIGNOFF'

        expected_cash = '0'
        if float_record:
            expected_cash = str(_compute_expected_cash(float_record))

        return Response({
            'has_shift': True,
            'float_status': float_status_val,
            'float_id': float_status['float_id'],
            'sheet_id': float_status['sheet_id'],
            'sheet_number': sheet_number,
            'opening_float': float_status['opening_float'],
            'opening_breakdown': float_status['opening_breakdown'],
            'expected_cash': expected_cash,
            'shift_end': shift_end,
            'minutes_remaining': mins_remaining,
            'should_prompt': mins_remaining <= 60,
            'should_lock': mins_remaining <= 0,
            'is_signed_off': False,
            'is_overtime': float_record.is_overtime if float_record else False,
            'overtime_until': float_record.overtime_until if float_record else None,
            'is_cover': float_record.is_cover if float_record else False,
            'cover_until': float_record.cover_until if float_record else None,
        })


# ============================================================================
# Petty Cash
# ============================================================================

class CashierHistoryView(APIView):
    """
    GET /api/v1/finance/cashier/history/
    Returns the logged-in cashier's personal collection history.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        level = request.query_params.get('level', 'year')

        qs = Receipt.objects.filter(
            cashier=user,
            is_void=False,
        ).select_related('daily_sheet')

        # Apply drill-down filters
        year_param = request.query_params.get('year')
        month_param = request.query_params.get('month')
        week_param = request.query_params.get('week')

        if year_param:
            qs = qs.filter(created_at__year=int(year_param))
        if month_param:
            qs = qs.filter(created_at__month=int(month_param))
        if week_param:
            qs = qs.filter(created_at__week=int(week_param))

        def _totals(queryset):
            return {
                'cash': float(queryset.filter(payment_method='CASH').aggregate(
                    t=Sum('amount_paid'))['t'] or 0),
                'momo': float(queryset.filter(payment_method='MOMO').aggregate(
                    t=Sum('amount_paid'))['t'] or 0),
                'pos': float(queryset.filter(payment_method='POS').aggregate(
                    t=Sum('amount_paid'))['t'] or 0),
                'count': queryset.count(),
            }

        # Year level
        if level == 'year':
            years = (
                qs.annotate(yr=ExtractYear('created_at'))
                  .values('yr')
                  .distinct()
                  .order_by('-yr')
            )
            result = []
            for row in years:
                y = row['yr']
                sub = qs.filter(created_at__year=y)
                t = _totals(sub)
                result.append({
                    'label': str(y),
                    'year': y,
                    'cash': t['cash'],
                    'momo': t['momo'],
                    'pos': t['pos'],
                    'total': t['cash'] + t['momo'] + t['pos'],
                    'count': t['count'],
                })
            return Response({'level': 'year', 'results': result})

        # Month level
        if level == 'month':
            months = (
                qs.annotate(mo=ExtractMonth('created_at'))
                  .values('mo')
                  .distinct()
                  .order_by('-mo')
            )
            result = []
            for row in months:
                m = row['mo']
                sub = qs.filter(created_at__month=m)
                t = _totals(sub)
                result.append({
                    'label': calendar.month_name[m],
                    'month': m,
                    'year': int(year_param) if year_param else None,
                    'cash': t['cash'],
                    'momo': t['momo'],
                    'pos': t['pos'],
                    'total': t['cash'] + t['momo'] + t['pos'],
                    'count': t['count'],
                })
            return Response({'level': 'month', 'results': result})

        # Week level
        if level == 'week':
            weeks = (
                qs.annotate(wk=ExtractWeek('created_at'))
                  .values('wk')
                  .distinct()
                  .order_by('-wk')
            )
            result = []
            for row in weeks:
                w = row['wk']
                sub = qs.filter(created_at__week=w)
                t = _totals(sub)
                result.append({
                    'label': f'Week {w}',
                    'week': w,
                    'month': int(month_param) if month_param else None,
                    'year': int(year_param) if year_param else None,
                    'cash': t['cash'],
                    'momo': t['momo'],
                    'pos': t['pos'],
                    'total': t['cash'] + t['momo'] + t['pos'],
                    'count': t['count'],
                })
            return Response({'level': 'week', 'results': result})

        # Day level
        if level == 'day':
            days = (
                qs.annotate(dy=TruncDay('created_at'))
                  .values('dy')
                  .distinct()
                  .order_by('-dy')
            )
            result = []
            for row in days:
                d = row['dy']
                sub = qs.filter(created_at__date=d.date())
                t = _totals(sub)
                result.append({
                    'label': d.strftime('%a, %d %b %Y'),
                    'date': d.date().isoformat(),
                    'cash': t['cash'],
                    'momo': t['momo'],
                    'pos': t['pos'],
                    'total': t['cash'] + t['momo'] + t['pos'],
                    'count': t['count'],
                })
            return Response({'level': 'day', 'results': result})

        return Response(
            {'detail': 'Invalid level. Use year, month, week, or day.'},
            status=status.HTTP_400_BAD_REQUEST,
        )


class PettyCashCreateView(APIView):
    """
    POST /api/v1/finance/sheets/<id>/petty-cash/
    Record a petty cash disbursement - requires BM approval.
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

        entry = PettyCash.objects.create(
            daily_sheet=sheet,
            cashier_float=float_record,
            amount=serializer.validated_data['amount'],
            category=serializer.validated_data['category'],
            purpose=serializer.validated_data['purpose'],
            approved_by=request.user,
            approved_at=timezone.now(),
            recorded_by=request.user,
        )

        return Response(
            PettyCashSerializer(entry).data,
            status=status.HTTP_201_CREATED,
        )


# ============================================================================
# POS Transactions
# ============================================================================

class POSTransactionListView(generics.ListAPIView):
    """
    GET /api/v1/finance/pos/
    Returns POS transactions for the user's branch.
    """
    serializer_class = POSTransactionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs = POSTransaction.objects.select_related('job', 'cashier')
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

        txn.status = POSTransaction.Status.SETTLED
        txn.settlement_date = serializer.validated_data['settlement_date']
        txn.settled_by = request.user
        txn.save(update_fields=[
            'status', 'settlement_date', 'settled_by', 'updated_at'
        ])

        return Response(POSTransactionSerializer(txn).data)


# ============================================================================
# Receipts
# ============================================================================

class ReceiptDetailView(generics.RetrieveAPIView):
    """
    GET /api/v1/finance/receipts/<id>/
    """
    serializer_class = ReceiptSerializer
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
            receipt = Receipt.objects.select_related('job__branch').get(pk=pk)
        except Receipt.DoesNotExist:
            return Response(
                {'detail': 'Receipt not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        engine = ReceiptEngine(receipt.job.branch)
        success = engine.send_whatsapp(receipt)

        if success:
            return Response({'detail': 'Receipt sent via WhatsApp.'})
        return Response(
            {'detail': 'WhatsApp delivery failed - check phone number.'},
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
            receipt = Receipt.objects.select_related('job__branch', 'cashier').get(pk=pk)
        except Receipt.DoesNotExist:
            return Response(
                {'detail': 'Receipt not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        engine = ReceiptEngine(receipt.job.branch)
        text = engine.format_thermal(receipt)

        return Response({'text': text})


class ReceiptListView(generics.ListAPIView):
    """
    GET /api/v1/finance/receipts/
    Branch-scoped receipt list.
    """
    serializer_class = ReceiptSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsPagination

    def get_queryset(self):
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
        now = timezone.now()
        today = now.date()

        if period == 'day':
            qs = qs.filter(created_at__date=today)
        elif period == 'week':
            week_start = today - timedelta(days=today.weekday())
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
    """
    serializer_class   = ReceiptSerializer
    permission_classes = [IsAuthenticated]
    pagination_class   = None

    def get_queryset(self):
        from django.utils import timezone
        from datetime import timedelta

        user = self.request.user
        qs = Receipt.objects.filter(
            cashier=user,
            is_void=False,
        ).select_related('job', 'daily_sheet').order_by('-created_at')

        period = self.request.query_params.get('period')
        date_param = self.request.query_params.get('date')

        if period:
            now = timezone.now()
            if period == 'day':
                qs = qs.filter(created_at__date=timezone.localdate())
            elif period == 'week':
                week_start = (now - timedelta(days=now.weekday())).replace(
                    hour=0, minute=0, second=0, microsecond=0)
                qs = qs.filter(created_at__gte=week_start)
            elif period == 'month':
                qs = qs.filter(
                    created_at__year=now.year,
                    created_at__month=now.month,
                )
        elif date_param:
            qs = qs.filter(created_at__date=date_param)

        return qs


# ============================================================================
# Credit Accounts
# ============================================================================

class CreditAccountListView(generics.ListAPIView):
    """
    GET /api/v1/finance/credit/
    """
    serializer_class = CreditAccountSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return CreditAccount.objects.select_related('customer', 'nominated_by', 'approved_by')


class CreditAccountDetailView(generics.RetrieveAPIView):
    """
    GET /api/v1/finance/credit/<id>/
    """
    serializer_class = CreditAccountSerializer
    permission_classes = [IsAuthenticated]
    queryset = CreditAccount.objects.select_related(
        'customer', 'recommended_by', 'approved_by'
    )


class CreditAccountCreateView(APIView):
    """
    POST /api/v1/finance/credit/
    BM recommends a credit account.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CreditAccountCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            customer = CustomerProfile.objects.get(pk=serializer.validated_data['customer_id'])
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
            customer=customer,
            account_type=serializer.validated_data['account_type'],
            credit_limit=serializer.validated_data['credit_limit'],
            payment_terms=serializer.validated_data.get('payment_terms', 30),
            organisation_name=serializer.validated_data.get('organisation_name', ''),
            contact_person=serializer.validated_data.get('contact_person', ''),
            contact_phone=serializer.validated_data.get('contact_phone', ''),
            notes=serializer.validated_data.get('notes', ''),
            recommended_by=request.user,
            approved_by=request.user,
            status=CreditAccount.Status.SUSPENDED,
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

        if serializer.validated_data['approved']:
            account.status = CreditAccount.Status.ACTIVE
            account.approved_by = request.user
            account.approved_at = timezone.now()
            account.notes = serializer.validated_data.get('notes', account.notes)
        else:
            account.status = CreditAccount.Status.CLOSED
            account.notes = serializer.validated_data.get('notes', account.notes)

        account.save()

        return Response(CreditAccountSerializer(account).data)


# ============================================================================
# Credit Settlements
# ============================================================================

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

        user = request.user
        sheet = self._get_today_sheet(user)
        if not sheet:
            return Response(
                {'detail': 'No open sheet for today - cannot process settlement.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            engine = CreditEngine(account)
            payment = engine.settle(
                amount=serializer.validated_data['amount'],
                payment_method=serializer.validated_data['payment_method'],
                actor=user,
                daily_sheet=sheet,
                momo_reference=serializer.validated_data.get('momo_reference', ''),
                pos_approval_code=serializer.validated_data.get('pos_approval_code', ''),
                notes=serializer.validated_data.get('notes', ''),
            )
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            CreditPaymentSerializer(payment).data,
            status=status.HTTP_201_CREATED,
        )

    def _get_today_sheet(self, user):
        try:
            return DailySalesSheet.objects.get(
                branch=user.branch,
                date=timezone.localdate(),
                status=DailySalesSheet.Status.OPEN,
            )
        except DailySalesSheet.DoesNotExist:
            return None


# ============================================================================
# Branch Transfer Credits
# ============================================================================

class BranchTransferCreditListView(generics.ListAPIView):
    """
    GET /api/v1/finance/transfers/
    Belt Manager sees all pending transfer credits for reconciliation.
    """
    serializer_class = BranchTransferCreditSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = BranchTransferCredit.objects.select_related(
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

        transfer.status = BranchTransferCredit.Status.RECONCILED
        transfer.reconciled_by = request.user
        transfer.reconciled_at = timezone.now()
        transfer.reconciliation_notes = request.data.get('notes', '')
        transfer.save(update_fields=[
            'status', 'reconciled_by', 'reconciled_at',
            'reconciliation_notes', 'updated_at',
        ])

        return Response(BranchTransferCreditSerializer(transfer).data)


class DailySalesSheetPDFView(APIView):
    """
    GET /api/v1/finance/sheets/<pk>/pdf/
    Generates and serves the day sheet as a read-only PDF.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            sheet = DailySalesSheet.objects.get(pk=pk)
        except DailySalesSheet.DoesNotExist:
            return Response({'detail': 'Sheet not found.'}, status=status.HTTP_404_NOT_FOUND)

        if request.user.branch != sheet.branch:
            return Response({'detail': 'Access denied.'}, status=status.HTTP_403_FORBIDDEN)

        if sheet.status not in (DailySalesSheet.Status.CLOSED, DailySalesSheet.Status.AUTO_CLOSED):
            return Response(
                {'detail': 'Sheet must be closed before downloading.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Download limit: 2 per BM, then view-only
        user_role = getattr(getattr(request.user, 'role', None), 'name', '')
        hq_roles = {'SUPER_ADMIN', 'REGIONAL_MANAGER', 'BELT_MANAGER',
                    'NATIONAL_FINANCE_HEAD', 'NATIONAL_FINANCE_DEPUTY'}
        is_hq = user_role in hq_roles

        download_count = SheetDownloadLog.objects.filter(
            sheet=sheet, downloaded_by=request.user
        ).count()

        view_only = (not is_hq) and (download_count >= 2)

        # Generate PDF if not cached
        media_root = getattr(settings, 'MEDIA_ROOT', 'media')
        sheets_dir = os.path.join(media_root, 'sheets')
        os.makedirs(sheets_dir, exist_ok=True)
        output_path = os.path.join(sheets_dir, f"sheet_{sheet.pk}_{sheet.date}.pdf")

        if not os.path.exists(output_path):
            call_command('generate_sheet_pdf', sheet_id=sheet.pk, output=output_path)

        # Log download (only if not view-only)
        if not view_only:
            ip = (request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip()
                  or request.META.get('REMOTE_ADDR'))
            SheetDownloadLog.objects.create(
                sheet=sheet, downloaded_by=request.user, ip_address=ip or None
            )

        # Serve
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
    Returns current branch lock state.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if not hasattr(user, 'branch') or not user.branch:
            return Response(
                {'detail': 'User has no branch assigned.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        role_map = {
            'ATTENDANT'     : 'ATTENDANT',
            'CASHIER'       : 'CASHIER',
            'BRANCH_MANAGER': 'BRANCH_MANAGER',
        }
        user_role = getattr(getattr(user, 'role', None), 'name', 'ATTENDANT')
        lock_role = role_map.get(user_role, 'ATTENDANT')
        status_data = SheetEngine(user.branch).get_branch_lock_status(role_name=lock_role)

        # Check cashier sign-off status
        today = timezone.localdate()
        cashier_signed_off = not CashierFloat.objects.filter(
            daily_sheet__branch=user.branch,
            daily_sheet__date=today,
            is_signed_off=False,
            opening_float__isnull=False,
        ).exists()
        status_data['cashier_signed_off'] = cashier_signed_off

        # Sheet info for topbar display
        try:
            from apps.finance.models import DailySalesSheet
            sheet = DailySalesSheet.objects.filter(
                branch=user.branch,
                date=today,
            ).values('sheet_number', 'status').first()
            status_data['sheet_number'] = sheet['sheet_number'] if sheet else None
            status_data['sheet_status'] = sheet['status'] if sheet else None
        except Exception:
            status_data['sheet_number'] = None
            status_data['sheet_status'] = None

        # Check for active float dispute - hard blocks BM portal
        float_dispute_active = CashierFloat.objects.filter(
            daily_sheet__branch=user.branch,
            daily_sheet__date=today,
            physical_confirm_disputed=True,
            morning_acknowledged=False,
        ).select_related('cashier').first()

        if float_dispute_active:
            status_data['float_dispute_active'] = True
            status_data['dispute_cashier_name'] = float_dispute_active.cashier.full_name
            status_data['dispute_float_amount'] = str(float_dispute_active.opening_float)
            status_data['dispute_float_id'] = float_dispute_active.pk
        else:
            status_data['float_dispute_active'] = False

        return Response(status_data)


class EODSummaryView(APIView):
    """
    GET /api/v1/finance/sheets/<pk>/eod-summary/
    Returns a comprehensive end-of-day summary.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
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


# ============================================================================
# Invoices
# ============================================================================

class InvoiceListView(generics.ListAPIView):
    """
    GET /api/v1/finance/invoices/
    Returns invoices for the requesting user's branch.
    """
    serializer_class = InvoiceSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsPagination

    def get_queryset(self):
        user = self.request.user
        qs = Invoice.objects.select_related(
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
        today = timezone.now().date()
        if period == 'day':
            qs = qs.filter(issue_date=today)
        elif period == 'week':
            week_start = today - timedelta(days=today.weekday())
            qs = qs.filter(issue_date__gte=week_start)
        elif period == 'month':
            qs = qs.filter(issue_date__year=today.year, issue_date__month=today.month)

        return qs.order_by('-issue_date', '-id')


class InvoiceDetailView(generics.RetrieveAPIView):
    """
    GET /api/v1/finance/invoices/<id>/
    """
    serializer_class = InvoiceSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Invoice.objects.select_related(
            'branch', 'job', 'generated_by'
        ).prefetch_related('line_items__service')


class InvoiceCreateView(APIView):
    """
    POST /api/v1/finance/invoices/
    Create a job-linked or standalone invoice.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
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
            data=serializer.validated_data,
            user=request.user,
            branch=branch,
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
            return Response({'detail': 'Invoice not found.'}, status=status.HTTP_404_NOT_FOUND)

        # Generate PDF if not exists
        if not invoice.pdf_path or not os.path.exists(invoice.pdf_path):
            try:
                _generate_invoice_pdf(invoice)
            except Exception as e:
                return Response(
                    {'detail': f'PDF generation failed: {e}'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        response = FileResponse(
            open(invoice.pdf_path, 'rb'),
            content_type='application/pdf',
        )
        response['Content-Disposition'] = (
            f'attachment; filename="{invoice.invoice_number}.pdf"'
        )
        return response


def _generate_invoice_pdf(invoice):
    """Generate a PDF for the invoice and save path to invoice.pdf_path."""
    import os, base64, io
    from django.conf import settings

    media_root   = getattr(settings, 'MEDIA_ROOT', 'media')
    invoices_dir = os.path.join(media_root, 'invoices')
    os.makedirs(invoices_dir, exist_ok=True)
    output_path  = os.path.join(invoices_dir, f"{invoice.invoice_number}.pdf")

    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle,
        Paragraph, Spacer, HRFlowable, Image,
    )
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT

    FARHAT_RED  = colors.HexColor('#E31E24')
    CHARCOAL    = colors.HexColor('#1A1A1A')
    DARK_GREY   = colors.HexColor('#444444')
    MID_GREY    = colors.HexColor('#777777')
    LIGHT_GREY  = colors.HexColor('#F0F0F0')
    WHITE       = colors.white

    PAGE_W, PAGE_H = A4
    LM = RM = 20 * mm
    CONTENT_W = PAGE_W - LM - RM

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=RM, leftMargin=LM,
        topMargin=0,    bottomMargin=20*mm,
    )

    def fmt(n):
        return f"GHS {float(n or 0):,.2f}"

    def style(name, **kw):
        return ParagraphStyle(name, **kw)

    sm        = style('sm',  fontSize=9,  fontName='Helvetica',      textColor=DARK_GREY)
    sm_bold   = style('smb', fontSize=9,  fontName='Helvetica-Bold', textColor=CHARCOAL)
    lbl       = style('lbl', fontSize=8,  fontName='Helvetica-Bold', textColor=colors.HexColor('#999999'), leading=10)
    right_sm  = style('rsm', fontSize=9,  fontName='Helvetica',      textColor=DARK_GREY,  alignment=TA_RIGHT)
    right_b   = style('rb',  fontSize=13, fontName='Helvetica-Bold', textColor=FARHAT_RED, alignment=TA_RIGHT)
    right_m   = style('rm',  fontSize=9,  fontName='Helvetica-Bold', textColor=CHARCOAL,   alignment=TA_RIGHT)
    center_sm = style('csm', fontSize=9,  fontName='Helvetica',      textColor=DARK_GREY,  alignment=TA_CENTER)
    total_lbl = style('tl',  fontSize=11, fontName='Helvetica-Bold', textColor=CHARCOAL)
    total_amt = style('ta',  fontSize=11, fontName='Helvetica-Bold', textColor=FARHAT_RED, alignment=TA_RIGHT)
    footer_sm = style('ft',  fontSize=8,  fontName='Helvetica',      textColor=MID_GREY,   alignment=TA_CENTER)

    story = []

    # -- Logo image from base64
    LOGO_B64 = "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"
    logo_bytes = base64.b64decode(LOGO_B64)
    logo_img   = Image(io.BytesIO(logo_bytes), width=14*mm, height=14*mm)

    # -- Header: red bar spanning full page width
    company_cell = [
        Paragraph('<font color="#FFFFFF"><b>Farhat Printing Press</b></font>',
                  style('co', fontSize=16, fontName='Helvetica-Bold',
                        textColor=WHITE, leading=20)),
        Paragraph('<font color="#FFFFFF">Professional Printing Services</font>',
                  style('cs', fontSize=8, fontName='Helvetica',
                        textColor=colors.HexColor('#FFAAAA'), leading=11)),
    ]
    invoice_type_color = '#FFFFFF'
    type_cell = Paragraph(
        f'<font color="#FFFFFF"><b>{invoice.invoice_type} INVOICE</b></font>',
        style('it', fontSize=11, fontName='Helvetica-Bold',
              textColor=WHITE, alignment=TA_RIGHT, leading=14),
    )

    header_data = [[ logo_img, company_cell, type_cell ]]
    header_table = Table(header_data, colWidths=[18*mm, CONTENT_W - 18*mm - 38*mm, 38*mm])
    header_table.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,-1), FARHAT_RED),
        ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
        ('LEFTPADDING',   (0,0), (0,0),   4),
        ('LEFTPADDING',   (1,0), (1,0),   8),
        ('RIGHTPADDING',  (2,0), (2,0),   8),
        ('TOPPADDING',    (0,0), (-1,-1), 10),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
    ]))
    story.append(header_table)

    # -- Branch info bar: centered pipe-separated text
    branch = invoice.branch
    branch_parts = [branch.name]
    if branch.phone or branch.whatsapp_number:
        branch_parts.append(branch.phone or branch.whatsapp_number)
    if branch.email:
        branch_parts.append(branch.email)
    branch_line = '  |  '.join(branch_parts)

    branch_bar_data = [[ Paragraph(branch_line,
        style('bb', fontSize=8.5, fontName='Helvetica',
              textColor=DARK_GREY, alignment=TA_CENTER)) ]]
    branch_bar = Table(branch_bar_data, colWidths=[CONTENT_W])
    branch_bar.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,-1), colors.HexColor('#FAFAFA')),
        ('TOPPADDING',    (0,0), (-1,-1), 7),
        ('BOTTOMPADDING', (0,0), (-1,-1), 7),
        ('LINEBELOW',     (0,0), (-1,-1), 0.5, LIGHT_GREY),
    ]))
    story.append(branch_bar)
    story.append(Spacer(1, 6*mm))

    # -- Bill To + Invoice meta two-column
    issued = invoice.issue_date.strftime('%d %b %Y') if invoice.issue_date else '-'
    due    = invoice.due_date.strftime('%d %b %Y')   if invoice.due_date   else '-'

    primary   = invoice.bill_to_company or invoice.bill_to_name
    secondary = invoice.bill_to_name if invoice.bill_to_company else None
    bill_lines = [Paragraph('BILL TO', lbl)]
    bill_lines.append(Paragraph(primary,
        style('bp', fontSize=12, fontName='Helvetica-Bold', textColor=CHARCOAL)))
    if secondary:
        bill_lines.append(Paragraph(secondary, sm_bold))
    if invoice.bill_to_phone:
        bill_lines.append(Paragraph(invoice.bill_to_phone, sm))
    if invoice.bill_to_email:
        bill_lines.append(Paragraph(invoice.bill_to_email, sm))

    meta_lines = [
        Paragraph('INVOICE NO', lbl),
        Paragraph(invoice.invoice_number,
            style('inv', fontSize=13, fontName='Helvetica-Bold',
                  textColor=FARHAT_RED, alignment=TA_RIGHT)),
        Spacer(1, 4),
        Paragraph('DATE ISSUED', lbl),
        Paragraph(issued, right_m),
        Spacer(1, 4),
        Paragraph('DUE DATE', lbl),
        Paragraph(due, right_m),
    ]

    meta_table = Table([[bill_lines, meta_lines]], colWidths=[CONTENT_W*0.55, CONTENT_W*0.45])
    meta_table.setStyle(TableStyle([
        ('VALIGN',       (0,0), (-1,-1), 'TOP'),
        ('LINEBEFORE',   (0,0), (0,-1),  2, FARHAT_RED),
        ('LEFTPADDING',  (0,0), (0,-1),  10),
        ('LEFTPADDING',  (1,0), (1,-1),  0),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 6*mm))

    # -- Job ref
    if invoice.job:
        story.append(Paragraph(
            f"Job Reference: <b>{invoice.job.job_number}</b>", sm))
        story.append(Spacer(1, 3*mm))

    # -- Line items table
    th = style('th', fontSize=9, fontName='Helvetica-Bold',
               textColor=WHITE)
    th_r = style('thr', fontSize=9, fontName='Helvetica-Bold',
                 textColor=WHITE, alignment=TA_RIGHT)
    th_c = style('thc', fontSize=9, fontName='Helvetica-Bold',
                 textColor=WHITE, alignment=TA_CENTER)

    table_data = [[
        Paragraph('SERVICE', th),
        Paragraph('QTY', th_c),
        Paragraph('UNIT PRICE', th_r),
        Paragraph('TOTAL', th_r),
    ]]

    for li in invoice.line_items.all():
        detail = f"{li.paper_size} &middot; {'Colour' if li.is_color else 'B&amp;W'}"
        if li.pages > 1:
            detail += f" &middot; {li.pages}pp &times; {li.sets} sets"
        table_data.append([
            [Paragraph(li.label, sm_bold), Paragraph(detail, sm)],
            Paragraph(str(li.quantity),
                style('qc', fontSize=9, fontName='Helvetica',
                      textColor=CHARCOAL, alignment=TA_CENTER)),
            Paragraph(fmt(li.unit_price),
                style('up', fontSize=9, fontName='Helvetica',
                      textColor=DARK_GREY, alignment=TA_RIGHT)),
            Paragraph(fmt(li.line_total),
                style('lt', fontSize=9, fontName='Helvetica-Bold',
                      textColor=CHARCOAL, alignment=TA_RIGHT)),
        ])

    col_w = [CONTENT_W*0.50, CONTENT_W*0.10, CONTENT_W*0.20, CONTENT_W*0.20]
    items_table = Table(table_data, colWidths=col_w, repeatRows=1)
    items_table.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,0),  FARHAT_RED),
        ('ROWBACKGROUNDS',(0,1), (-1,-1), [WHITE, colors.HexColor('#FAFAFA')]),
        ('LINEBELOW',     (0,0), (-1,-1), 0.5, LIGHT_GREY),
        ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING',    (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('LEFTPADDING',   (0,0), (-1,-1), 8),
        ('RIGHTPADDING',  (0,0), (-1,-1), 8),
    ]))
    story.append(items_table)
    story.append(Spacer(1, 4*mm))

    # -- Totals
    totals_data = [[
        Paragraph('Subtotal', sm),
        Paragraph(fmt(invoice.subtotal), right_sm),
    ]]
    if invoice.vat_rate:
        totals_data.append([
            Paragraph(f'VAT ({invoice.vat_rate}%)', sm),
            Paragraph(fmt(invoice.vat_amount), right_sm),
        ])
    totals_data.append([
        Paragraph('<b>Total</b>', total_lbl),
        Paragraph(f'<b>{fmt(invoice.total)}</b>', total_amt),
    ])

    totals_table = Table(totals_data, colWidths=[CONTENT_W*0.75, CONTENT_W*0.25])
    totals_table.setStyle(TableStyle([
        ('ALIGN',         (1,0),  (1,-1),  'RIGHT'),
        ('LINEABOVE',     (0,-1), (-1,-1), 1.5, FARHAT_RED),
        ('LINEBELOW',     (0,0),  (-1,-2), 0.5, LIGHT_GREY),
        ('TOPPADDING',    (0,0),  (-1,-1), 5),
        ('BOTTOMPADDING', (0,0),  (-1,-1), 5),
    ]))
    story.append(totals_table)

    # -- BM note
    if invoice.bm_note:
        story.append(Spacer(1, 5*mm))
        story.append(HRFlowable(width=CONTENT_W, thickness=0.5,
                                color=LIGHT_GREY))
        story.append(Spacer(1, 3*mm))
        story.append(Paragraph(invoice.bm_note, sm))

    # -- Footer
    story.append(Spacer(1, 8*mm))
    footer_data = [[
        Paragraph(
            'Thank you for choosing Farhat Printing Press',
            style('fl', fontSize=8, fontName='Helvetica',
                  textColor=WHITE, alignment=TA_LEFT)),
        Paragraph(
            'FARHAT &trade;',
            style('fr', fontSize=9, fontName='Helvetica-Bold',
                  textColor=FARHAT_RED, alignment=TA_RIGHT)),
    ]]
    footer_table = Table(footer_data, colWidths=[CONTENT_W*0.7, CONTENT_W*0.3])
    footer_table.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,-1), CHARCOAL),
        ('TOPPADDING',    (0,0), (-1,-1), 10),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
        ('LEFTPADDING',   (0,0), (0,-1),  14),
        ('RIGHTPADDING',  (-1,0),(-1,-1), 14),
        ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
    ]))
    story.append(footer_table)

    doc.build(story)

    invoice.pdf_path = output_path
    invoice.save(update_fields=['pdf_path', 'updated_at'])

def _deliver_invoice(invoice):
    """Send invoice via its delivery channel. Marks status as SENT."""
    invoice.status = Invoice.SENT
    invoice.sent_at = timezone.now()
    invoice.save(update_fields=['status', 'sent_at', 'updated_at'])


# ============================================================================
# Weekly Report
# ============================================================================

class WeeklyReportListView(generics.ListAPIView):
    """
    GET /api/v1/finance/weekly/
    Returns weekly reports for the requesting user's branch.
    """
    serializer_class = WeeklyReportListSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs = WeeklyReport.objects.select_related('branch', 'submitted_by').prefetch_related('daily_sheets')
        if hasattr(user, 'branch') and user.branch:
            qs = qs.filter(branch=user.branch)
        return qs


class WeeklyReportDetailView(generics.RetrieveAPIView):
    """
    GET /api/v1/finance/weekly/<id>/
    Full weekly report detail including daily sheets.
    """
    serializer_class = WeeklyReportDetailSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs = WeeklyReport.objects.select_related('branch', 'submitted_by').prefetch_related('daily_sheets')
        if hasattr(user, 'branch') and user.branch:
            qs = qs.filter(branch=user.branch)
        return qs


class WeeklyReportPrepareView(APIView):
    """
    POST /api/v1/finance/weekly/prepare/
    Creates or refreshes a DRAFT weekly report for the current week.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        branch = getattr(request.user, 'branch', None)
        if not branch:
            return Response(
                {'detail': 'No branch assigned.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        report, created = WeeklyReportService.prepare(branch)
        return Response(
            WeeklyReportDetailSerializer(report).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class WeeklyReportNotesView(APIView):
    """
    PATCH /api/v1/finance/weekly/<id>/notes/
    BM adds or updates notes on a draft report.
    """
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        try:
            report = WeeklyReport.objects.get(pk=pk, branch=request.user.branch)
        except WeeklyReport.DoesNotExist:
            return Response({'detail': 'Report not found.'}, status=status.HTTP_404_NOT_FOUND)

        if report.is_locked:
            return Response({'detail': 'Report is locked.'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = WeeklyReportNotesSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        report.bm_notes = serializer.validated_data['bm_notes']
        report.save(update_fields=['bm_notes', 'updated_at'])
        return Response(WeeklyReportDetailSerializer(report).data)


class WeeklyReportSubmitView(APIView):
    """
    POST /api/v1/finance/weekly/<id>/submit/
    BM submits and locks the weekly report.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            report = WeeklyReport.objects.prefetch_related('daily_sheets').get(
                pk=pk, branch=request.user.branch
            )
        except WeeklyReport.DoesNotExist:
            return Response({'detail': 'Report not found.'}, status=status.HTTP_404_NOT_FOUND)

        report, errors = WeeklyReportService.submit(report, submitted_by=request.user)
        if errors:
            return Response({'detail': errors[0]}, status=status.HTTP_400_BAD_REQUEST)

        return Response(WeeklyReportDetailSerializer(report).data)


class WeeklyReportPDFView(APIView):
    """
    GET /api/v1/finance/weekly/<id>/pdf/
    Download the weekly report PDF.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            report = WeeklyReport.objects.get(pk=pk, branch=request.user.branch)
        except WeeklyReport.DoesNotExist:
            return Response({'detail': 'Report not found.'}, status=status.HTTP_404_NOT_FOUND)

        if not report.pdf_path or not os.path.exists(report.pdf_path):
            try:
                _generate_weekly_pdf(report)
            except Exception as e:
                return Response({'detail': f'PDF generation failed: {e}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        response = FileResponse(
            open(report.pdf_path, 'rb'),
            content_type='application/pdf',
        )
        response['Content-Disposition'] = (
            f'attachment; filename="weekly_{report.branch.code}_W{report.week_number}_{report.year}.pdf"'
        )
        return response


def _generate_weekly_pdf(report):
    """Generate the weekly filing PDF."""
    media_root = getattr(settings, 'MEDIA_ROOT', 'media')
    weekly_dir = os.path.join(media_root, 'weekly')
    os.makedirs(weekly_dir, exist_ok=True)

    output_path = os.path.join(
        weekly_dir,
        f"weekly_{report.branch.code}_W{report.week_number}_{report.year}.pdf"
    )

    branch = report.branch
    W, H = A4

    # Colors
    FARHAT_RED = colors.HexColor('#E31E24')
    FARHAT_GOLD = colors.HexColor('#F5A623')
    WHITE = colors.white
    BLACK = colors.HexColor('#111111')
    GREY = colors.HexColor('#666666')
    LIGHT_GREY = colors.HexColor('#f5f5f5')
    BORDER_GREY = colors.HexColor('#e0e0e0')

    def fmt(n):
        return f"GHS {float(n or 0):,.2f}"

    # Custom cover page flowable
    class CoverPage(Flowable):
        def __init__(self, width, height, branch, report):
            Flowable.__init__(self)
            self.width = width
            self.height = height
            self.branch = branch
            self.report = report

        def draw(self):
            c = self.canvas
            W = self.width
            H = self.height

            # White background
            c.setFillColor(WHITE)
            c.rect(0, 0, W, H, fill=1, stroke=0)

            # Red center panel (60% width, full height)
            panel_x = W * 0.20
            panel_w = W * 0.60
            c.setFillColor(FARHAT_RED)
            c.rect(panel_x, 0, panel_w, H, fill=1, stroke=0)

            # Logo area (white bird silhouette approximation)
            logo_cx = panel_x + panel_w / 2
            logo_cy = H * 0.72
            logo_r = 28

            c.setFillColor(WHITE)
            c.circle(logo_cx, logo_cy, logo_r, fill=1, stroke=0)

            # Draw stylized F in the circle
            c.setFillColor(FARHAT_RED)
            c.setFont('Helvetica-Bold', 22)
            c.drawCentredString(logo_cx, logo_cy - 8, 'F')

            # Branch name
            branch_name = self.branch.name.upper()
            words = branch_name.split()
            if len(words) >= 2:
                line1 = ' '.join(words[:-1])
                line2 = words[-1]
            else:
                line1 = branch_name
                line2 = ''

            c.setFillColor(WHITE)
            c.setFont('Helvetica-Bold', 32)
            c.drawCentredString(logo_cx, H * 0.55, line1)
            if line2:
                c.drawCentredString(logo_cx, H * 0.47, line2)

            # Week / Month / Year
            month_name = calendar.month_name[self.report.date_from.month].upper()
            week_str = f"WEEK {self.report.week_number},  {month_name},  {self.report.year}"

            c.setFillColor(FARHAT_GOLD)
            c.setFont('Helvetica-Bold', 14)
            c.drawCentredString(logo_cx, H * 0.36, week_str)

            # Contact info
            email = self.branch.email or 'info@farhatprintingpress.com'
            phone = self.branch.phone or self.branch.whatsapp_number or '+233 556244194'

            c.setFillColor(WHITE)
            c.setFont('Helvetica-Bold', 11)
            c.drawCentredString(logo_cx, H * 0.26, email)
            c.drawCentredString(logo_cx, H * 0.21, phone)

            # Footer
            c.setFillColor(FARHAT_GOLD)
            c.setFont('Helvetica-Bold', 7)
            c.drawCentredString(logo_cx, H * 0.07, 'MANDATORY WEEKLY FILING')
            c.drawCentredString(logo_cx, H * 0.055, 'STRICTLY CONFIDENTIAL')

            c.setFillColor(WHITE)
            c.setFont('Helvetica', 7)
            c.drawCentredString(logo_cx, H * 0.035, 'Property of Farhat Printing Press')

    # Build document
    doc = BaseDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=20*mm,
        leftMargin=20*mm,
        topMargin=20*mm,
        bottomMargin=20*mm,
    )

    # Cover page template - full bleed, no margins
    cover_frame = Frame(0, 0, W, H, leftPadding=0, rightPadding=0,
                        topPadding=0, bottomPadding=0, id='cover')
    content_frame = Frame(20*mm, 20*mm, W - 40*mm, H - 40*mm, id='normal')

    doc.addPageTemplates([
        PageTemplate(id='Cover', frames=cover_frame),
        PageTemplate(id='Later', frames=content_frame),
    ])

    styles = getSampleStyleSheet()

    story = []

    # Page 1 - Cover (full bleed)
    story.append(CoverPage(W, H, branch, report))
    story.append(PageBreak())

    # Content page styles
    CW = A4[0] - 40*mm

    h1_style = ParagraphStyle('h1', fontSize=18, fontName='Helvetica-Bold',
                               textColor=BLACK, spaceAfter=4)
    label_style = ParagraphStyle('lbl', fontSize=8, fontName='Helvetica-Bold',
                                  textColor=GREY, letterSpacing=0.5, spaceAfter=8)
    body_style = ParagraphStyle('body', fontSize=9, fontName='Helvetica', textColor=GREY)
    right_style = ParagraphStyle('right', fontSize=9, fontName='Helvetica',
                                  alignment=TA_RIGHT, textColor=BLACK)
    right_bold = ParagraphStyle('rightb', fontSize=10, fontName='Helvetica-Bold',
                                 alignment=TA_RIGHT, textColor=BLACK)

    # Page 2 header
    month_name = calendar.month_name[report.date_from.month]
    story.append(Paragraph(f"{branch.name}", h1_style))
    story.append(Paragraph(
        f"Weekly Filing - Week {report.week_number}, {month_name} {report.year}  "
        f"({report.date_from.strftime('%d %b')} - {report.date_to.strftime('%d %b %Y')})",
        label_style
    ))
    story.append(HRFlowable(width=CW, thickness=2, color=FARHAT_RED))
    story.append(Spacer(1, 6*mm))

    # Revenue summary
    story.append(Paragraph('REVENUE SUMMARY', label_style))

    rev_data = [
        ['Method', 'Amount (GHS)', '% of Total'],
        ['Cash', f"{float(report.total_cash):,.2f}",
         f"{float(report.total_cash)/float(report.total_collected)*100:.1f}%" if report.total_collected else '0%'],
        ['Mobile Money', f"{float(report.total_momo):,.2f}",
         f"{float(report.total_momo)/float(report.total_collected)*100:.1f}%" if report.total_collected else '0%'],
        ['POS', f"{float(report.total_pos):,.2f}",
         f"{float(report.total_pos)/float(report.total_collected)*100:.1f}%" if report.total_collected else '0%'],
        ['TOTAL COLLECTED', f"{float(report.total_collected):,.2f}", '100%'],
        ['Petty Cash Out', f"({float(report.total_petty_cash_out):,.2f})", ''],
        ['Net Cash in Till', f"{float(report.net_cash_in_till):,.2f}", ''],
    ]

    rev_table = Table(rev_data, colWidths=[CW*0.45, CW*0.30, CW*0.25])
    rev_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), LIGHT_GREY),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('FONTNAME', (0, 4), (-1, 4), 'Helvetica-Bold'),
        ('BACKGROUND', (0, 4), (-1, 4), colors.HexColor('#fff0f0')),
        ('TEXTCOLOR', (0, 4), (-1, 4), FARHAT_RED),
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER_GREY),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(rev_table)
    story.append(Spacer(1, 6*mm))

    # Daily breakdown
    story.append(Paragraph('DAILY BREAKDOWN', label_style))

    day_headers = ['Date', 'Day', 'Status', 'Cash', 'MoMo', 'POS', 'Total', 'Jobs']
    day_data = [day_headers]

    sheets = report.daily_sheets.all().order_by('date')
    for sheet in sheets:
        day_name = sheet.date.strftime('%A')
        total = float(sheet.total_cash + sheet.total_momo + sheet.total_pos)
        day_data.append([
            sheet.date.strftime('%d %b'),
            day_name,
            sheet.status,
            f"{float(sheet.total_cash):,.2f}",
            f"{float(sheet.total_momo):,.2f}",
            f"{float(sheet.total_pos):,.2f}",
            f"{total:,.2f}",
            str(sheet.total_jobs_created),
        ])

    if day_data[1:]:
        day_table = Table(
            day_data,
            colWidths=[CW*0.1, CW*0.12, CW*0.11, CW*0.14, CW*0.14, CW*0.12, CW*0.14, CW*0.09]
        )
        day_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), LIGHT_GREY),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('ALIGN', (3, 0), (-1, -1), 'RIGHT'),
            ('GRID', (0, 0), (-1, -1), 0.5, BORDER_GREY),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [WHITE, colors.HexColor('#fafafa')]),
        ]))
        story.append(day_table)
    else:
        story.append(Paragraph('No daily sheets linked.', body_style))

    story.append(Spacer(1, 6*mm))

    # Jobs summary
    story.append(Paragraph('JOBS SUMMARY', label_style))

    jobs_data = [
        ['Metric', 'Count'],
        ['Total Jobs Created', str(report.total_jobs_created)],
        ['Completed', str(report.total_jobs_complete)],
        ['Cancelled', str(report.total_jobs_cancelled)],
        ['Carry Forward (Unpaid)', str(report.carry_forward_count)],
    ]

    jobs_table = Table(jobs_data, colWidths=[CW*0.65, CW*0.35])
    jobs_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), LIGHT_GREY),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER_GREY),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [WHITE, colors.HexColor('#fafafa')]),
    ]))
    story.append(jobs_table)
    story.append(Spacer(1, 6*mm))

    # Inventory
    story.append(Paragraph('INVENTORY', label_style))
    snapshot = report.inventory_snapshot
    items = snapshot.get('items', []) if snapshot else []
    low_stock = snapshot.get('low_stock', []) if snapshot else []

    if items:
        inv_headers = ['Consumable', 'Category', 'Unit', 'Opening', 'Received', 'Consumed', 'Closing', 'Status']
        inv_data = [inv_headers]
        for item in items:
            is_low = item.get('is_low', False)
            status_label = 'LOW' if is_low else 'OK'
            inv_data.append([
                item.get('consumable', '--'),
                item.get('category', '--'),
                item.get('unit', '--'),
                str(item.get('opening', 0)),
                str(item.get('received', 0)),
                str(item.get('consumed', 0)),
                str(item.get('closing', 0)),
                status_label,
            ])

        col_w = [CW*0.28, CW*0.12, CW*0.07, CW*0.08, CW*0.09, CW*0.09, CW*0.08, CW*0.09]
        inv_table = Table(inv_data, colWidths=col_w, repeatRows=1)

        # Build row styles - highlight low stock rows red
        row_styles = [
            ('BACKGROUND', (0, 0), (-1, 0), LIGHT_GREY),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('ALIGN', (3, 0), (-1, -1), 'RIGHT'),
            ('GRID', (0, 0), (-1, -1), 0.5, BORDER_GREY),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [WHITE, colors.HexColor('#fafafa')]),
        ]
        for i, item in enumerate(items, start=1):
            if item.get('is_low', False):
                row_styles.append(('TEXTCOLOR', (7, i), (7, i), FARHAT_RED))
                row_styles.append(('FONTNAME', (7, i), (7, i), 'Helvetica-Bold'))

        inv_table.setStyle(TableStyle(row_styles))
        story.append(inv_table)

        if low_stock:
            story.append(Spacer(1, 3*mm))
            story.append(Paragraph(
                f"<font color='#E31E24'><b>Low stock alert:</b></font> {', '.join(low_stock)}",
                body_style
            ))
    else:
        inv_placeholder = Table([['No inventory data available for this period.']], colWidths=[CW])
        inv_placeholder.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#fffbec')),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#7a5c00')),
            ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#f0d878')),
            ('TOPPADDING', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
            ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ]))
        story.append(inv_placeholder)

    story.append(Spacer(1, 6*mm))

    # BM Notes
    story.append(Paragraph('BRANCH MANAGER NOTES', label_style))
    notes_text = report.bm_notes or '--'
    notes_table = Table([[notes_text]], colWidths=[CW])
    notes_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f9f9f9')),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('TEXTCOLOR', (0, 0), (-1, -1), BLACK),
        ('BOX', (0, 0), (-1, -1), 0.5, BORDER_GREY),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
    ]))
    story.append(notes_table)
    story.append(Spacer(1, 8*mm))

    # Sign-off block
    story.append(HRFlowable(width=CW, thickness=1, color=BORDER_GREY))
    story.append(Spacer(1, 4*mm))

    submitted_by = report.submitted_by.full_name if report.submitted_by else '--'
    submitted_at = (
        report.submitted_at.strftime('%d %b %Y, %I:%M %p')
        if report.submitted_at else '--'
    )

    signoff_data = [
        ['Filed by', submitted_by, 'Date', submitted_at],
        ['Branch', branch.name, 'Week', f"W{report.week_number}/{report.year}"],
    ]
    signoff_table = Table(signoff_data, colWidths=[CW*0.15, CW*0.35, CW*0.15, CW*0.35])
    signoff_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('TEXTCOLOR', (0, 0), (0, -1), GREY),
        ('TEXTCOLOR', (2, 0), (2, -1), GREY),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(signoff_table)
    story.append(Spacer(1, 4*mm))
    story.append(Paragraph(
        'This document is the property of Farhat Printing Press. '
        'Strictly confidential - for internal use only.',
        ParagraphStyle('ft', fontSize=7, fontName='Helvetica',
                       textColor=GREY, alignment=TA_CENTER)
    ))

    doc.build(story)

    # Save path
    report.pdf_path = output_path
    report.save(update_fields=['pdf_path', 'updated_at'])


# ============================================================================
# Monthly Close
# ============================================================================

class MonthlyCloseStatusView(APIView):
    """
    GET /api/v1/finance/monthly-close/?month=3&year=2026
    Returns the monthly close record + integrity check status.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        branch = getattr(request.user, 'branch', None)
        if not branch:
            return Response({'detail': 'No branch assigned.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            month = int(request.query_params.get('month', timezone.localdate().month))
            year = int(request.query_params.get('year', timezone.localdate().year))
        except ValueError:
            return Response({'detail': 'Invalid month or year.'}, status=status.HTTP_400_BAD_REQUEST)

        engine = MonthlyCloseEngine(branch, month, year)
        close, _ = engine.get_or_create()
        integrity = engine.check_integrity()

        return Response({
            'id': close.pk,
            'month': close.month,
            'year': close.year,
            'month_name': close.month_name,
            'status': close.status,
            'can_submit': close.can_submit,
            'can_endorse': close.can_endorse,
            'can_reject': close.can_reject,
            'is_locked': close.is_locked,
            'integrity': integrity,
            'submitted_by': close.submitted_by.full_name if close.submitted_by else None,
            'submitted_at': close.submitted_at.isoformat() if close.submitted_at else None,
            'endorsed_by': close.endorsed_by.full_name if close.endorsed_by else None,
            'endorsed_at': close.endorsed_at.isoformat() if close.endorsed_at else None,
            'rejected_by': close.rejected_by.full_name if close.rejected_by else None,
            'rejected_at': close.rejected_at.isoformat() if close.rejected_at else None,
            'rejection_reason': close.rejection_reason,
            'bm_notes': close.bm_notes,
            'finance_reviewer': close.finance_reviewer.full_name if close.finance_reviewer else None,
            'finance_cleared_at': close.finance_cleared_at.isoformat() if close.finance_cleared_at else None,
            'clarification_request': close.clarification_request,
            'clarification_response': close.clarification_response,
            'clarification_due_at': close.clarification_due_at.isoformat() if close.clarification_due_at else None,
            'rm_notes': close.rm_notes,
            'summary_snapshot': close.summary_snapshot,
        })


class MonthlyClosePrepareView(APIView):
    """
    POST /api/v1/finance/monthly-close/prepare/
    Builds and persists summary_snapshot on an OPEN monthly close.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        branch = getattr(request.user, 'branch', None)
        if not branch:
            return Response({'detail': 'No branch assigned.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            month = int(request.data.get('month', timezone.localdate().month))
            year = int(request.data.get('year', timezone.localdate().year))
        except (ValueError, TypeError):
            return Response({'detail': 'Invalid month or year.'}, status=status.HTTP_400_BAD_REQUEST)

        engine = MonthlyCloseEngine(branch, month, year)
        close, _ = engine.get_or_create()

        if close.status != 'OPEN':
            return Response(
                {'detail': f'Cannot prepare - current status is {close.status}.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        integrity = engine.check_integrity()
        if not integrity['can_submit']:
            errors = [c['detail'] for c in integrity['checks'].values() if not c['pass']]
            return Response({'detail': errors}, status=status.HTTP_400_BAD_REQUEST)

        snapshot = engine.build_snapshot()
        close.summary_snapshot = snapshot
        close.save(update_fields=['summary_snapshot'])

        return Response({
            'id': close.pk,
            'month': close.month,
            'year': close.year,
            'status': close.status,
            'can_submit': close.can_submit,
            'integrity': integrity,
            'summary_snapshot': close.summary_snapshot,
        })


class MonthlyCloseSubmitView(APIView):
    """
    POST /api/v1/finance/monthly-close/submit/
    BM submits the monthly close.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        branch = getattr(request.user, 'branch', None)
        if not branch:
            return Response({'detail': 'No branch assigned.'}, status=status.HTTP_400_BAD_REQUEST)

        today = timezone.localdate()
        month = request.data.get('month', today.month)
        year = request.data.get('year', today.year)
        notes = request.data.get('bm_notes', '')

        engine = MonthlyCloseEngine(branch, int(month), int(year))
        close, errors = engine.submit(request.user, notes)

        if errors:
            return Response({'detail': errors}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            'id': close.pk,
            'status': close.status,
            'submitted_at': close.submitted_at.isoformat(),
            'message': f"{close.month_name} {close.year} submitted successfully. Assigned to Finance for review.",
        })


class MonthlyCloseEndorseView(APIView):
    """
    POST /api/v1/finance/monthly-close/<id>/endorse/
    Belt Manager endorses the monthly close.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        role = getattr(getattr(request.user, 'role', None), 'name', '')
        if role not in ('REGIONAL_MANAGER', 'SUPER_ADMIN'):
            return Response(
                {'detail': 'Only a Regional Manager can endorse monthly closes.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            close = MonthlyClose.objects.get(pk=pk)
        except MonthlyClose.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        notes = request.data.get('rm_notes', '')
        engine = MonthlyCloseEngine(close.branch, close.month, close.year)
        close, errors = engine.endorse(request.user, notes)

        if errors:
            return Response({'detail': errors}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            'id': close.pk,
            'status': close.status,
            'endorsed_at': close.endorsed_at.isoformat(),
            'message': f"{close.month_name} {close.year} endorsed. Awaiting lock on PDF download.",
        })


class MonthlyCloseRejectView(APIView):
    """
    POST /api/v1/finance/monthly-close/<id>/reject/
    Belt Manager rejects the monthly close.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            close = MonthlyClose.objects.get(pk=pk)
        except MonthlyClose.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        reason = request.data.get('reason', '').strip()
        if not reason:
            return Response({'detail': 'Rejection reason is required.'}, status=status.HTTP_400_BAD_REQUEST)

        engine = MonthlyCloseEngine(close.branch, close.month, close.year)
        close, errors = engine.reject(request.user, reason)

        if errors:
            return Response({'detail': errors}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            'id': close.pk,
            'status': close.status,
            'rejected_at': close.rejected_at.isoformat(),
            'message': 'Monthly close rejected. BM has been notified.',
        })


class MonthlyClosePDFView(APIView):
    """
    GET /api/v1/finance/monthly-close/<id>/pdf/
    Generate and download the monthly close PDF.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            close = MonthlyClose.objects.get(pk=pk)
        except MonthlyClose.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        if not close.summary_snapshot:
            return Response(
                {'detail': 'No snapshot available - monthly close has not been submitted yet.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        engine = MonthlyCloseEngine(close.branch, close.month, close.year)
        pdf_bytes = engine.generate_pdf(close)

        filename = f"monthly_close_{close.branch.code}_{calendar.month_name[close.month]}_{close.year}.pdf"

        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


class MonthlyClosePendingView(APIView):
    """
    GET /api/v1/finance/monthly-close/pending/
    Belt Manager: list all monthly closes awaiting endorsement.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        pending = MonthlyClose.objects.filter(
            status=MonthlyClose.Status.FINANCE_CLEARED,
        ).select_related(
            'branch', 'submitted_by', 'finance_reviewer'
        ).order_by('-year', '-month')

        data = [
            {
                'id': c.pk,
                'branch': c.branch.name,
                'branch_code': c.branch.code,
                'month': c.month,
                'year': c.year,
                'month_name': c.month_name,
                'submitted_by': c.submitted_by.full_name if c.submitted_by else '--',
                'submitted_at': c.submitted_at.isoformat() if c.submitted_at else None,
                'finance_reviewer': c.finance_reviewer.full_name if c.finance_reviewer else '--',
                'finance_cleared_at': c.finance_cleared_at.isoformat() if c.finance_cleared_at else None,
                'bm_notes': c.bm_notes,
                'finance_notes': c.finance_notes,
                'total_collected': str(
                    c.summary_snapshot.get('revenue', {}).get('total_collected', 0)
                ),
                'total_jobs': c.summary_snapshot.get('jobs', {}).get('total', 0),
            }
            for c in pending
        ]
        return Response(data)


class FloatAcknowledgeView(APIView):
    """
    POST /api/v1/finance/floats/<id>/acknowledge/
    Cashier confirms receipt of opening float with denomination breakdown.
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

        breakdown = request.data.get('breakdown')
        if not breakdown or not isinstance(breakdown, dict):
            return Response(
                {'detail': 'Denomination breakdown is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        result = FloatEngine.acknowledge(
            float_record=float_record,
            breakdown=breakdown,
            cashier=request.user,
        )

        if not result['ok']:
            return Response(
                {'detail': result['error']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        f = result['float']
        return Response({
            'detail': 'Float acknowledged. Have a great shift!',
            'float_id': f.pk,
            'opening_float': str(f.opening_float),
            'morning_acknowledged': True,
            'acknowledged_at': f.morning_acknowledged_at.isoformat(),
        })


class MonthlyCloseDetailView(APIView):
    """
    GET /api/v1/finance/monthly-close/<pk>/
    Returns full monthly close detail including summary_snapshot.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            close = MonthlyClose.objects.select_related(
                'branch', 'submitted_by', 'endorsed_by', 'rejected_by'
            ).get(pk=pk)
        except MonthlyClose.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        return Response({
            'id': close.pk,
            'branch': close.branch.name,
            'branch_code': close.branch.code,
            'month': close.month,
            'year': close.year,
            'month_name': close.month_name,
            'status': close.status,
            'submitted_by': close.submitted_by.full_name if close.submitted_by else '--',
            'submitted_at': close.submitted_at.isoformat() if close.submitted_at else None,
            'endorsed_by': close.endorsed_by.full_name if close.endorsed_by else None,
            'endorsed_at': close.endorsed_at.isoformat() if close.endorsed_at else None,
            'rejected_by': close.rejected_by.full_name if close.rejected_by else None,
            'rejected_at': close.rejected_at.isoformat() if close.rejected_at else None,
            'rejection_reason': close.rejection_reason,
            'bm_notes': close.bm_notes,
            'summary_snapshot': close.summary_snapshot,
        })


class MonthlyCloseMyQueueView(APIView):
    """
    GET /api/v1/finance/monthly-close/my-queue/
    Finance: list closes assigned to the current user.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        role = getattr(getattr(request.user, 'role', None), 'name', '')
        if role not in FINANCE_ROLES:
            return Response(
                {'detail': 'Access denied.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        scope = get_finance_scope(request.user)

        if role in REGIONAL_ROLES:
            closes = MonthlyClose.objects.filter(
                scope['branch_filter'],
                status__in=[
                    MonthlyClose.Status.FINANCE_REVIEWING,
                    MonthlyClose.Status.RESUBMITTED,
                ],
            ).select_related(
                'branch', 'submitted_by', 'finance_reviewer'
            ).order_by('-year', '-month')
        else:
            closes = MonthlyClose.objects.filter(
                finance_reviewer=request.user,
                status__in=[
                    MonthlyClose.Status.FINANCE_REVIEWING,
                    MonthlyClose.Status.RESUBMITTED,
                ],
            ).select_related(
                'branch', 'submitted_by', 'finance_reviewer'
            ).order_by('-year', '-month')

        data = []
        for c in closes:
            risk_score = None
            try:
                summary = MonthlyCloseSummary.objects.filter(monthly_close=c).first()
                if summary:
                    risk_score = summary.risk_score
            except Exception:
                pass

            snap = c.summary_snapshot or {}
            revenue = snap.get('revenue', {})
            jobs = snap.get('jobs', {})

            data.append({
                'id': c.pk,
                'branch': c.branch.name,
                'branch_code': c.branch.code,
                'month': c.month,
                'year': c.year,
                'month_name': c.month_name,
                'status': c.status,
                'submitted_by': c.submitted_by.full_name if c.submitted_by else '--',
                'submitted_at': c.submitted_at.isoformat() if c.submitted_at else None,
                'bm_notes': c.bm_notes,
                'clarification_request': c.clarification_request,
                'clarification_response': c.clarification_response,
                'clarification_due_at': c.clarification_due_at.isoformat() if c.clarification_due_at else None,
                'risk_score': risk_score,
                'total_collected': revenue.get('total_collected', '0'),
                'total_cash': revenue.get('total_cash', '0'),
                'total_momo': revenue.get('total_momo', '0'),
                'total_pos': revenue.get('total_pos', '0'),
                'total_petty_cash_out': revenue.get('total_petty_cash_out', '0'),
                'total_credit_issued': revenue.get('total_credit_issued', '0'),
                'total_credit_settled': revenue.get('total_credit_settled', '0'),
                'cash_pct': revenue.get('cash_pct', 0),
                'momo_pct': revenue.get('momo_pct', 0),
                'pos_pct': revenue.get('pos_pct', 0),
                'total_jobs': jobs.get('total', 0),
                'jobs_complete': jobs.get('complete', 0),
                'jobs_cancelled': jobs.get('cancelled', 0),
                'completion_rate': jobs.get('completion_rate', 0),
                'top_services': snap.get('top_services', [])[:3],
                'weekly_breakdown': snap.get('weekly_breakdown', []),
            })

        data.sort(key=lambda x: (x['risk_score'] or 0), reverse=True)
        return Response(data)


class MonthlyCloseMyHistoryView(APIView):
    """
    GET /api/v1/finance/monthly-close/my-history/
    Finance: list closes this user has cleared.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        role = getattr(getattr(request.user, 'role', None), 'name', '')
        if role not in FINANCE_ROLES:
            return Response(
                {'detail': 'Access denied.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        scope = get_finance_scope(request.user)

        if role in REGIONAL_ROLES:
            closes = MonthlyClose.objects.filter(
                scope['branch_filter'],
                status__in=[
                    MonthlyClose.Status.FINANCE_CLEARED,
                    MonthlyClose.Status.ENDORSED,
                    MonthlyClose.Status.LOCKED,
                ],
            ).select_related('branch', 'submitted_by').order_by('-year', '-month')
        else:
            closes = MonthlyClose.objects.filter(
                finance_reviewer=request.user,
                status__in=[
                    MonthlyClose.Status.FINANCE_CLEARED,
                    MonthlyClose.Status.ENDORSED,
                    MonthlyClose.Status.LOCKED,
                ],
            ).select_related('branch', 'submitted_by').order_by('-year', '-month')

        data = [
            {
                'id': c.pk,
                'branch': c.branch.name,
                'branch_code': c.branch.code,
                'month': c.month,
                'year': c.year,
                'month_name': c.month_name,
                'status': c.status,
                'submitted_by': c.submitted_by.full_name if c.submitted_by else '--',
                'submitted_at': c.submitted_at.isoformat() if c.submitted_at else None,
                'finance_cleared_at': c.finance_cleared_at.isoformat() if c.finance_cleared_at else None,
                'total_collected': str(
                    c.summary_snapshot.get('revenue', {}).get('total_collected', 0)
                ),
                'total_jobs': c.summary_snapshot.get('jobs', {}).get('total', 0),
            }
            for c in closes
        ]
        return Response(data)


class MonthlyCloseMyBranchesView(APIView):
    """
    GET /api/v1/finance/monthly-close/my-branches/
    Finance: all closes assigned to this user, grouped by branch.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        role = getattr(getattr(request.user, 'role', None), 'name', '')
        if role not in FINANCE_ROLES:
            return Response(
                {'detail': 'Access denied.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        scope = get_finance_scope(request.user)

        if role in REGIONAL_ROLES:
            all_closes = MonthlyClose.objects.filter(
                scope['branch_filter'],
            ).select_related(
                'branch', 'submitted_by', 'finance_reviewer'
            ).order_by('branch__name', '-year', '-month')
        else:
            all_closes = MonthlyClose.objects.filter(
                finance_reviewer=request.user,
            ).select_related(
                'branch', 'submitted_by', 'finance_reviewer'
            ).order_by('branch__name', '-year', '-month')

        branches = defaultdict(lambda: {'active': None, 'history': []})

        active_statuses = {
            MonthlyClose.Status.FINANCE_REVIEWING,
            MonthlyClose.Status.RESUBMITTED,
            MonthlyClose.Status.NEEDS_CLARIFICATION,
        }
        history_statuses = {
            MonthlyClose.Status.FINANCE_CLEARED,
            MonthlyClose.Status.ENDORSED,
            MonthlyClose.Status.LOCKED,
        }

        for c in all_closes:
            key = c.branch.code
            snap = c.summary_snapshot or {}
            revenue = snap.get('revenue', {})
            jobs = snap.get('jobs', {})

            if c.status in active_statuses:
                branches[key]['branch'] = c.branch.name
                branches[key]['branch_code'] = c.branch.code
                branches[key]['active'] = {
                    'id': c.pk,
                    'month': c.month,
                    'year': c.year,
                    'month_name': c.month_name,
                    'status': c.status,
                    'submitted_by': c.submitted_by.full_name if c.submitted_by else '--',
                    'submitted_at': c.submitted_at.isoformat() if c.submitted_at else None,
                    'bm_notes': c.bm_notes,
                    'clarification_request': c.clarification_request,
                    'clarification_response': c.clarification_response,
                    'clarification_due_at': c.clarification_due_at.isoformat() if c.clarification_due_at else None,
                    'total_collected': revenue.get('total_collected', '0'),
                    'total_cash': revenue.get('total_cash', '0'),
                    'total_momo': revenue.get('total_momo', '0'),
                    'total_pos': revenue.get('total_pos', '0'),
                    'total_petty_cash_out': revenue.get('total_petty_cash_out', '0'),
                    'total_credit_settled': revenue.get('total_credit_settled', '0'),
                    'cash_pct': revenue.get('cash_pct', 0),
                    'momo_pct': revenue.get('momo_pct', 0),
                    'pos_pct': revenue.get('pos_pct', 0),
                    'total_jobs': jobs.get('total', 0),
                    'jobs_complete': jobs.get('complete', 0),
                    'jobs_cancelled': jobs.get('cancelled', 0),
                    'completion_rate': jobs.get('completion_rate', 0),
                    'top_services': snap.get('top_services', [])[:3],
                    'weekly_breakdown': snap.get('weekly_breakdown', []),
                }
            elif c.status in history_statuses:
                if 'branch' not in branches[key]:
                    branches[key]['branch'] = c.branch.name
                    branches[key]['branch_code'] = c.branch.code
                branches[key]['history'].append({
                    'id': c.pk,
                    'month': c.month,
                    'year': c.year,
                    'month_name': c.month_name,
                    'status': c.status,
                    'total_collected': revenue.get('total_collected', '0'),
                    'finance_cleared_at': c.finance_cleared_at.isoformat() if c.finance_cleared_at else None,
                })

        result = []
        for key, data in branches.items():
            if 'branch' not in data:
                continue
            result.append({
                'branch': data['branch'],
                'branch_code': data['branch_code'],
                'active': data['active'],
                'history': data['history'],
            })

        result.sort(key=lambda x: (0 if x['active'] else 1, x['branch']))

        return Response(result)


class MonthlyCloseClearView(APIView):
    """
    POST /api/v1/finance/monthly-close/<id>/clear/
    Finance clears the monthly close.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        role = getattr(getattr(request.user, 'role', None), 'name', '')
        if role not in FINANCE_ROLES:
            return Response(
                {'detail': 'Only Finance reviewers can clear monthly closes.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            close = MonthlyClose.objects.get(pk=pk)
        except MonthlyClose.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        # Ensure this Finance user is the assigned reviewer
        if close.finance_reviewer != request.user and role != 'SUPER_ADMIN':
            return Response(
                {'detail': 'This close is not assigned to you.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        notes = request.data.get('finance_notes', '')
        engine = MonthlyCloseEngine(close.branch, close.month, close.year)
        close, errors = engine.clear(request.user, notes)

        if errors:
            return Response({'detail': errors}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            'id': close.pk,
            'status': close.status,
            'finance_cleared_at': close.finance_cleared_at.isoformat(),
            'message': f"{close.month_name} {close.year} cleared. Regional Manager notified.",
        })


class MonthlyCloseRequestClarificationView(APIView):
    """
    POST /api/v1/finance/monthly-close/<id>/request-clarification/
    Finance flags items requiring BM clarification.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        role = getattr(getattr(request.user, 'role', None), 'name', '')
        if role not in FINANCE_ROLES:
            return Response(
                {'detail': 'Only Finance reviewers can request clarification.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            close = MonthlyClose.objects.get(pk=pk)
        except MonthlyClose.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        if close.finance_reviewer != request.user and role != 'SUPER_ADMIN':
            return Response(
                {'detail': 'This close is not assigned to you.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        clarification = request.data.get('clarification', '').strip()
        if not clarification:
            return Response(
                {'detail': 'Clarification request cannot be empty.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        engine = MonthlyCloseEngine(close.branch, close.month, close.year)
        close, errors = engine.request_clarification(request.user, clarification)

        if errors:
            return Response({'detail': errors}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            'id': close.pk,
            'status': close.status,
            'clarification_due_at': close.clarification_due_at.isoformat(),
            'message': 'Clarification requested. Branch Manager has 24 hours to respond.',
        })


class FloatPhysicalConfirmView(APIView):
    """
    POST /api/v1/finance/floats/<id>/physical-confirm/
    Cashier confirms or disputes physical receipt of float.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            float_record = CashierFloat.objects.select_related(
                'daily_sheet', 'cashier'
            ).get(pk=pk, cashier=request.user)
        except CashierFloat.DoesNotExist:
            return Response(
                {'detail': 'Float record not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if float_record.morning_acknowledged:
            return Response(
                {'detail': 'Float already acknowledged.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        received = request.data.get('received', True)

        if received:
            return Response({
                'detail': 'Receipt confirmed. Please count your float.',
                'float_status': 'PENDING_ACK',
                'float_id': float_record.pk,
                'opening_float': str(float_record.opening_float),
            })
        else:
            float_record.physical_confirm_disputed = True
            float_record.physical_confirm_disputed_at = timezone.now()
            float_record.save(update_fields=[
                'physical_confirm_disputed',
                'physical_confirm_disputed_at',
                'updated_at',
            ])

            self._notify_rm_dispute(float_record)
            self._notify_bm_dispute(float_record)

            return Response({
                'detail': 'Dispute recorded. RM and BM have been notified.',
                'float_status': 'PENDING_PHYSICAL_CONFIRM',
                'disputed': True,
            })

    def _notify_rm_dispute(self, float_record):
        try:
            branch = float_record.daily_sheet.branch
            rm_users = CustomUser.objects.filter(
                role__name='REGIONAL_MANAGER',
                is_active=True,
                region=branch.region,
            )
            for rm in rm_users:
                notify(
                    recipient=rm,
                    verb='FLOAT_DISPUTE',
                    message=(
                        f"{float_record.cashier.full_name} at {branch.name} "
                        f"reported not receiving their opening float of "
                        f"GHS {float_record.opening_float}. "
                        f"Branch Manager has been notified and portal blocked."
                    ),
                    link='/portal/regional-manager/',
                )
        except Exception:
            logger.exception('FloatPhysicalConfirmView: failed to notify RM of dispute')

    def _notify_bm_dispute(self, float_record):
        try:
            branch = float_record.daily_sheet.branch
            bm = CustomUser.objects.filter(
                branch=branch,
                role__name='BRANCH_MANAGER',
                is_active=True,
            ).first()
            if bm:
                notify(
                    recipient=bm,
                    verb='FLOAT_DISPUTE',
                    message=(
                        f"{float_record.cashier.full_name} reported not receiving "
                        f"their opening float of GHS {float_record.opening_float}. "
                        f"Please hand over the float and ask them to re-confirm. "
                        f"Your portal is blocked until this is resolved."
                    ),
                    link='/portal/dashboard/',
                )
        except Exception:
            logger.exception('FloatPhysicalConfirmView: failed to notify BM of dispute')


class FloatReConfirmView(APIView):
    """
    POST /api/v1/finance/floats/<id>/re-confirm/
    Cashier re-confirms physical receipt after BM has handed over the float.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            float_record = CashierFloat.objects.select_related(
                'daily_sheet', 'cashier'
            ).get(pk=pk, cashier=request.user)
        except CashierFloat.DoesNotExist:
            return Response(
                {'detail': 'Float record not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not float_record.physical_confirm_disputed:
            return Response(
                {'detail': 'No active dispute on this float.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if float_record.morning_acknowledged:
            return Response(
                {'detail': 'Float already acknowledged.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        float_record.physical_confirm_disputed = False
        float_record.save(update_fields=['physical_confirm_disputed', 'updated_at'])

        self._notify_rm_resolved(float_record)

        return Response({
            'detail': 'Receipt confirmed. Please count your float.',
            'float_status': 'PENDING_ACK',
            'float_id': float_record.pk,
            'opening_float': str(float_record.opening_float),
        })

    def _notify_rm_resolved(self, float_record):
        try:
            branch = float_record.daily_sheet.branch
            rm_users = CustomUser.objects.filter(
                role__name='REGIONAL_MANAGER',
                is_active=True,
                region=branch.region,
            )
            for rm in rm_users:
                notify(
                    recipient=rm,
                    verb='FLOAT_DISPUTE_RESOLVED',
                    message=(
                        f"Float dispute at {branch.name} resolved. "
                        f"{float_record.cashier.full_name} has confirmed receipt of "
                        f"GHS {float_record.opening_float}. BM portal unblocked."
                    ),
                    link='/portal/regional-manager/',
                )
        except Exception:
            logger.exception('FloatReConfirmView: failed to notify RM of resolution')
