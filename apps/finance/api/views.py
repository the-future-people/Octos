from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

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

# ─────────────────────────────────────────────────────────────────────────────
# Daily Sales Sheet
# ─────────────────────────────────────────────────────────────────────────────

class DailySalesSheetListView(generics.ListAPIView):
    """
    GET /api/v1/finance/sheets/
    Returns sheets for the requesting user's branch.
    Belt/Region managers see all sheets across their scope.
    """
    serializer_class   = DailySalesSheetListSerializer
    permission_classes = [IsAuthenticated]

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
    Returns today's open sheet for the user's branch.
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

        sheet, _ = SheetEngine(user.branch).get_or_open_today(
            opened_by=user,
        )

        if sheet is None:
            return Response(
                {'detail': 'No sheet today — branch may be closed (Sunday).'},
                status=status.HTTP_404_NOT_FOUND,
            )

        from django.db.models import Sum
        from apps.jobs.models import Job

        data = DailySalesSheetDetailSerializer(
            sheet, context={'request': request}
        ).data

       # If sheet is still open, inject live totals from actual jobs
        if sheet.status == DailySalesSheet.Status.OPEN:
            jobs = Job.objects.filter(
                daily_sheet=sheet,
                status=Job.COMPLETE,
            )
            data['total_cash']         = str(jobs.filter(payment_method='CASH').aggregate(t=Sum('amount_paid'))['t'] or 0)
            data['total_momo']         = str(jobs.filter(payment_method='MOMO').aggregate(t=Sum('amount_paid'))['t'] or 0)
            data['total_pos']          = str(jobs.filter(payment_method='POS').aggregate(t=Sum('amount_paid'))['t'] or 0)
            data['total_jobs_created'] = jobs.count()
            data['net_cash_in_till']   = str(jobs.filter(payment_method='CASH').aggregate(t=Sum('amount_paid'))['t'] or 0)

        return Response(data)


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
    BM manually closes the sheet.
    Blocked if non-carryover pending payments exist.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
            from django.utils import timezone
            from datetime import timedelta
            from apps.accounts.models import CustomUser

            try:
                sheet = DailySalesSheet.objects.select_related('branch').get(pk=pk)
            except DailySalesSheet.DoesNotExist:
                return Response(
                    {'detail': 'Sheet not found.'},
                    status=status.HTTP_404_NOT_FOUND,
                )

            # ── Validate floats payload ───────────────────────────────
            floats_data = request.data.get('floats', [])
            for f in floats_data:
                amount = float(f.get('opening_float', 0))
                if amount < 20 or amount > 100 or amount % 5 != 0:
                    return Response(
                        {'detail': f"Float amount GHS {amount} is invalid. Must be GHS 20–100 in multiples of GHS 5."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

            try:
                notes  = request.data.get('notes', '').strip()
                engine = SheetEngine(sheet.branch)
                closed = engine.close_sheet(
                    sheet,
                    closed_by = request.user,
                    auto      = False,
                )
                if notes:
                    closed.notes = notes
                    closed.save(update_fields=['notes'])

                # ── Stage tomorrow's floats (no sheet created yet) ────
                if floats_data:
                    tomorrow = sheet.date + timedelta(days=1)

                    # Never stage floats for Sunday
                    if tomorrow.weekday() == 6:
                        pass  # Sunday — no float, no sheet
                    else:
                        for f in floats_data:
                            try:
                                cashier = CustomUser.objects.get(pk=f['cashier_id'])
                                # Remove any existing staged float for this cashier/date
                                CashierFloat.objects.filter(
                                    cashier        = cashier,
                                    scheduled_date = tomorrow,
                                    daily_sheet    = None,
                                ).delete()
                                CashierFloat.objects.create(
                                    cashier        = cashier,
                                    daily_sheet    = None,
                                    scheduled_date = tomorrow,
                                    opening_float  = float(f['opening_float']),
                                    float_set_by   = request.user,
                                    float_set_at   = timezone.now(),
                                )
                            except CustomUser.DoesNotExist:
                                pass  # If cashier not found, skip staging float for them

                return Response(
                    DailySalesSheetDetailSerializer(
                        closed, context={'request': request}
                    ).data
                )
            except ValueError as e:
                return Response(
                    {'detail': str(e)},
                    status=status.HTTP_400_BAD_REQUEST,
                )


# ─────────────────────────────────────────────────────────────────────────────
# Cashier Float
# ─────────────────────────────────────────────────────────────────────────────

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

# ─────────────────────────────────────────────────────────────────────────────
# Cashier Sign-Off
# ─────────────────────────────────────────────────────────────────────────────

class CashierSignOffView(APIView):
    """
    POST /api/v1/finance/floats/<id>/sign-off/
    Cashier submits closing cash, variance notes, shift notes.
    Marks float as signed off and locks the queue for this cashier.
    If overtime or cover: extends queue access until specified time.
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

        serializer = CashierSignOffSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        d = serializer.validated_data
        from django.utils import timezone

        # Overtime or cover — not signing off yet, just extending
        if d.get('is_overtime') or d.get('is_cover'):
            float_record.is_overtime     = d.get('is_overtime', False)
            float_record.overtime_reason = d.get('overtime_reason', '')
            float_record.overtime_until  = d.get('overtime_until')
            float_record.is_cover        = d.get('is_cover', False)
            float_record.cover_until     = d.get('cover_until')

            if d.get('covering_for_id'):
                from apps.accounts.models import CustomUser
                try:
                    float_record.covering_for = CustomUser.objects.get(
                        pk=d['covering_for_id']
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
                'detail'         : 'Shift extended.',
                'is_overtime'    : float_record.is_overtime,
                'overtime_until' : float_record.overtime_until,
                'is_cover'       : float_record.is_cover,
                'cover_until'    : float_record.cover_until,
            })

        # Full sign-off
        float_record.closing_cash   = d['closing_cash']
        float_record.variance_notes = d['variance_notes']
        float_record.shift_notes    = d['shift_notes']
        float_record.signed_off_by  = request.user
        float_record.signed_off_at  = timezone.now()
        float_record.is_signed_off  = True
        float_record.compute_variance()
        float_record.save(update_fields=[
            'closing_cash', 'variance_notes', 'shift_notes',
            'signed_off_by', 'signed_off_at', 'is_signed_off',
            'variance', 'updated_at',
        ])

        return Response(CashierFloatSerializer(float_record).data)


class CashierShiftStatusView(APIView):
    """
    GET /api/v1/finance/cashier/shift-status/
    Returns current shift state for the logged-in cashier.
    Polled every 60s by the cashier portal.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.utils import timezone
        from datetime import datetime, timedelta, time as dt_time
        from apps.hr.models import EmployeeShift, ShiftOverride

        user   = request.user
        branch = getattr(user, 'branch', None)

        if not branch:
            return Response(
                {'detail': 'No branch assigned.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Get today's float
        today = timezone.localdate()
        try:
            float_record = CashierFloat.objects.get(
                cashier             = user,
                daily_sheet__date   = today,
                daily_sheet__branch = branch,
            )
        except CashierFloat.DoesNotExist:
            float_record = None

        # If already signed off
        if float_record and float_record.is_signed_off:
            return Response({
                'has_shift'        : True,
                'shift_end'        : None,
                'minutes_remaining': 0,
                'should_prompt'    : False,
                'should_lock'      : True,
                'is_signed_off'    : True,
                'float_id'         : float_record.id,
                'sheet_id'         : float_record.daily_sheet_id,
                'is_overtime'      : False,
                'overtime_until'   : None,
                'is_cover'         : False,
                'cover_until'      : None,
            })

        # If overtime active — use overtime_until instead of shift end
        if float_record and float_record.is_overtime and float_record.overtime_until:
            now            = timezone.now()
            delta          = float_record.overtime_until - now
            mins_remaining = max(0, int(delta.total_seconds() / 60))
            return Response({
                'has_shift'        : True,
                'shift_end'        : float_record.overtime_until.time(),
                'minutes_remaining': mins_remaining,
                'should_prompt'    : mins_remaining <= 60,
                'should_lock'      : mins_remaining <= 0,
                'is_signed_off'    : False,
                'float_id'         : float_record.id,
                'sheet_id'         : float_record.daily_sheet_id,
                'is_overtime'      : True,
                'overtime_until'   : float_record.overtime_until,
                'is_cover'         : float_record.is_cover,
                'cover_until'      : float_record.cover_until,
            })

        # Resolve shift end via ShiftEngine
        from apps.hr.shift_engine import ShiftEngine as HRShiftEngine
        from datetime import datetime as dt

        cash_schedule  = HRShiftEngine(branch).get_role_schedule('CASHIER', target_date=today)
        signoff_dt     = dt.fromisoformat(cash_schedule['signoff_at'])
        now            = timezone.now()
        delta          = signoff_dt - now
        mins_remaining = max(0, int(delta.total_seconds() / 60))
        shift_end      = dt.fromisoformat(cash_schedule['shift_end']).time()

        # Resolve sheet_id — from float if available, else today's open sheet
        sheet_id = None
        if float_record:
            sheet_id = float_record.daily_sheet_id
        else:
            try:
                from apps.finance.models import DailySalesSheet
                open_sheet = DailySalesSheet.objects.get(
                    branch=branch, date=today, status='OPEN'
                )
                sheet_id = open_sheet.pk
            except DailySalesSheet.DoesNotExist:
                pass

        return Response({
            'has_shift'        : True,
            'shift_end'        : shift_end,
            'minutes_remaining': mins_remaining,
            'should_prompt'    : mins_remaining <= 60,
            'should_lock'      : mins_remaining <= 0,
            'is_signed_off'    : float_record.is_signed_off if float_record else False,
            'float_id'         : float_record.id if float_record else None,
            'sheet_id'         : sheet_id,
            'is_overtime'      : float_record.is_overtime if float_record else False,
            'overtime_until'   : float_record.overtime_until if float_record else None,
            'is_cover'         : float_record.is_cover if float_record else False,
            'cover_until'      : float_record.cover_until if float_record else None,
        })
# ─────────────────────────────────────────────────────────────────────────────
# Petty Cash
# ─────────────────────────────────────────────────────────────────────────────
class CashierHistoryView(APIView):
    """
    GET /api/v1/finance/cashier/history/
    Returns the logged-in cashier's personal collection history.

    Query params:
      ?level=year                     — yearly totals
      ?level=month&year=2026          — monthly breakdown for a year
      ?level=week&year=2026&month=3   — weekly breakdown for a month
      ?level=day&year=2026&month=3&week=12 — daily breakdown for a week (ISO week)
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

        # ── Apply drill-down filters ──────────────────────────
        year_param  = request.query_params.get('year')
        month_param = request.query_params.get('month')
        week_param  = request.query_params.get('week')

        if year_param:
            qs = qs.filter(created_at__year=int(year_param))
        if month_param:
            qs = qs.filter(created_at__month=int(month_param))
        if week_param:
            qs = qs.filter(created_at__week=int(week_param))

        # ── Aggregate per method ──────────────────────────────
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

        # ── Year level ────────────────────────────────────────
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

        # ── Month level ───────────────────────────────────────
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

        # ── Week level ────────────────────────────────────────
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

        # ── Day level ─────────────────────────────────────────
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
    Record a petty cash disbursement — requires BM approval.
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


# ─────────────────────────────────────────────────────────────────────────────
# POS Transactions
# ─────────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────────
# Receipts
# ─────────────────────────────────────────────────────────────────────────────

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
            {'detail': 'WhatsApp delivery failed — check phone number.'},
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
    """
    serializer_class   = ReceiptSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        from django.utils import timezone
        from datetime import timedelta
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
        since  = {
            'day'  : now - timedelta(days=1),
            'week' : now - timedelta(weeks=1),
            'month': now - timedelta(days=30),
        }.get(period)

        if since:
            qs = qs.filter(created_at__gte=since)

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
# ─────────────────────────────────────────────────────────────────────────────
# Credit Accounts
# ─────────────────────────────────────────────────────────────────────────────

class CreditAccountListView(generics.ListAPIView):
    """
    GET /api/v1/finance/credit/
    """
    serializer_class   = CreditAccountSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return CreditAccount.objects.select_related(
            'customer', 'recommended_by', 'approved_by'
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
            approved_by       = request.user,  # placeholder — overwritten on approval
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


# ─────────────────────────────────────────────────────────────────────────────
# Credit Settlements
# ─────────────────────────────────────────────────────────────────────────────

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
                {'detail': 'No open sheet for today — cannot process settlement.'},
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


# ─────────────────────────────────────────────────────────────────────────────
# Branch Transfer Credits
# ─────────────────────────────────────────────────────────────────────────────

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

        # Only allow access to own branch
        if request.user.branch != sheet.branch:
            return Response({'detail': 'Access denied.'}, status=403)

        # Only closed sheets can be downloaded
        if sheet.status != DailySalesSheet.Status.CLOSED:
            return Response(
                {'detail': 'Sheet must be closed before downloading.'},
                status=400
            )

        # Generate PDF
        import os
        from django.conf import settings
        from io import BytesIO
        from django.core.management import call_command

        media_root = getattr(settings, 'MEDIA_ROOT', 'media')
        sheets_dir = os.path.join(media_root, 'sheets')
        os.makedirs(sheets_dir, exist_ok=True)
        output_path = os.path.join(sheets_dir, f"sheet_{sheet.pk}_{sheet.date}.pdf")

        # Regenerate if file doesn't exist
        if not os.path.exists(output_path):
            call_command('generate_sheet_pdf', sheet_id=sheet.pk, output=output_path)

        # Serve the file
        from django.http import FileResponse
        response = FileResponse(
            open(output_path, 'rb'),
            content_type='application/pdf',
        )
        response['Content-Disposition'] = (
            f'attachment; filename="sheet_{sheet.branch.code}_{sheet.date}.pdf"'
        )
        return response

class BranchLockStatusView(APIView):
    """
    GET /api/v1/finance/lock-status/
    Returns current branch lock state — can jobs be created?
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

        status_data = SheetEngine(user.branch).get_branch_lock_status()
        return Response(status_data)

class EODSummaryView(APIView):
    """
    GET /api/v1/finance/sheets/<pk>/eod-summary/
    Returns a comprehensive end-of-day summary for the pre-close checklist.
    Only accessible by the branch manager of the sheet's branch.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        from django.db.models import Sum, Count, Q
        from apps.jobs.models import Job
        from apps.finance.models import (
            CashierFloat, PettyCash, POSTransaction, CreditAccount
        )

        # ── Fetch sheet ───────────────────────────────────────────
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

        branch = sheet.branch
        jobs   = Job.objects.filter(daily_sheet=sheet).select_related(
            'intake_by', 'customer', 'assigned_to'
        )

        # ── Revenue summary ───────────────────────────────────────
        # ── Revenue summary — computed live from jobs ─────────────────────────────
        from decimal import Decimal
        def _sum_method(method):
            return jobs.filter(
                status='COMPLETE', payment_method=method, amount_paid__isnull=False
            ).aggregate(t=Sum('amount_paid'))['t'] or Decimal('0.00')

        live_cash   = _sum_method('CASH')
        live_momo   = _sum_method('MOMO')
        live_pos    = _sum_method('POS')
        live_credit = jobs.filter(
            status='COMPLETE', payment_method='CREDIT', amount_paid__isnull=False
        ).aggregate(t=Sum('amount_paid'))['t'] or Decimal('0.00')
        live_petty    = sheet.total_petty_cash_out  # petty cash has its own model
        live_settled  = sheet.total_credit_settled  # credit settlements
        live_net      = live_cash + live_settled - live_petty
        revenue = {
            'cash'            : str(live_cash),
            'momo'            : str(live_momo),
            'pos'             : str(live_pos),
            'total'           : str(live_cash + live_momo + live_pos),
            'credit_issued'   : str(live_credit),
            'credit_settled'  : str(live_settled),
            'petty_cash_out'  : str(live_petty),
            'net_cash_in_till': str(live_net),
        }

        # ── Jobs summary ──────────────────────────────────────────
        total_jobs     = jobs.count()
        completed_jobs = jobs.filter(status='COMPLETE').count()
        cancelled_jobs = jobs.filter(status='CANCELLED').count()
        local_jobs     = jobs.filter(is_routed=False).count()
        routed_out     = jobs.filter(is_routed=True).count()

        # Routed-in: jobs assigned to this branch from another branch
        routed_in = Job.objects.filter(
            assigned_to=branch,
            is_routed=True,
        ).exclude(branch=branch).count()

        # Pending payment — cashier accepted (in queue)
        pending_cashier = jobs.filter(status='PENDING_PAYMENT')
        pending_cashier_list = list(pending_cashier.values(
            'id', 'job_number', 'title', 'estimated_cost',
            'intake_by__first_name', 'intake_by__last_name',
            'created_at',
        ))
        for j in pending_cashier_list:
            fn = j.pop('intake_by__first_name', '') or ''
            ln = j.pop('intake_by__last_name', '') or ''
            j['intake_by_name'] = f"{fn} {ln}".strip() or '—'
            j['estimated_cost'] = str(j['estimated_cost'] or 0)
            j['created_at']     = j['created_at'].isoformat() if j['created_at'] else None

        # Pending payment — never touched by cashier (no POSTransaction)
        pending_untouched = pending_cashier.filter(
            pos_transactions__isnull=True
        )
        pending_untouched_list = list(pending_untouched.values(
            'id', 'job_number', 'title', 'estimated_cost',
            'intake_by__first_name', 'intake_by__last_name',
            'created_at',
        ))
        for j in pending_untouched_list:
            fn = j.pop('intake_by__first_name', '') or ''
            ln = j.pop('intake_by__last_name', '') or ''
            j['intake_by_name'] = f"{fn} {ln}".strip() or '—'
            j['estimated_cost'] = str(j['estimated_cost'] or 0)
            j['created_at']     = j['created_at'].isoformat() if j['created_at'] else None

        jobs_summary = {
            'total'            : total_jobs,
            'completed'        : completed_jobs,
            'cancelled'        : cancelled_jobs,
            'local'            : local_jobs,
            'routed_out'       : routed_out,
            'routed_in'        : routed_in,
            'pending_payment'  : pending_cashier.count(),
            'pending_untouched': pending_untouched.count(),
            'pending_list'     : pending_cashier_list,
            'untouched_list'   : pending_untouched_list,
        }

        # ── Cashier activity ──────────────────────────────────────
        floats = CashierFloat.objects.filter(
            daily_sheet=sheet
        ).select_related('cashier', 'float_set_by', 'signed_off_by')

        cashier_activity = []
        for f in floats:
            from apps.finance.models import Receipt
            txns = Receipt.objects.filter(
                daily_sheet=sheet,
                cashier=f.cashier,
            ).order_by('created_at')

            by_method = txns.order_by().values('payment_method').annotate(
                total=Sum('amount_paid'),
                count=Count('id'),
            )
            method_breakdown = {
                row['payment_method']: {
                    'total': str(row['total'] or 0),
                    'count': row['count'],
                }
                for row in by_method
            }

            first_txn = txns.first()
            last_txn  = txns.last()

            cashier_activity.append({
                'cashier_name'     : f.cashier.full_name,
                'cashier_id'       : f.cashier.id,
                'opening_float'    : str(f.opening_float),
                'closing_cash'     : str(f.closing_cash),
                'expected_cash'    : str(f.expected_cash),
                'variance'         : str(f.variance),
                'variance_notes'   : f.variance_notes,
                'is_signed_off'    : f.is_signed_off,
                'signed_off_at'    : f.signed_off_at.isoformat() if f.signed_off_at else None,
                'float_set_at'     : f.float_set_at.isoformat() if f.float_set_at else None,
                'active_from'      : first_txn.created_at.isoformat() if first_txn else None,
                'active_to'        : last_txn.created_at.isoformat() if last_txn else None,
                'total_collected'  : str(txns.aggregate(t=Sum('amount_paid'))['t'] or 0),
                'transaction_count': txns.count(),
                'method_breakdown' : method_breakdown,
            })
        float_opened = floats.exists()

        # ── Petty cash ────────────────────────────────────────────
        petty_cash_records = PettyCash.objects.filter(
            daily_sheet=sheet
        ).select_related('recorded_by').order_by('created_at')

        petty_cash_list = list(petty_cash_records.values(
            'id', 'amount', 'purpose', 'created_at',
            'recorded_by__first_name', 'recorded_by__last_name',
        ))
        for p in petty_cash_list:
            fn = p.pop('recorded_by__first_name', '') or ''
            ln = p.pop('recorded_by__last_name', '') or ''
            p['recorded_by_name'] = f"{fn} {ln}".strip() or '—'
            p['reason']           = p.pop('purpose', '—')
            p['amount']           = str(p['amount'])
            p['created_at']       = p['created_at'].isoformat() if p['created_at'] else None

        # ── Credit sales ──────────────────────────────────────────
        credit_jobs = jobs.filter(
            customer__credit_account__isnull=False,
            status__in=['COMPLETE', 'PENDING_PAYMENT'],
        ).select_related('customer__credit_account')

        credit_list = []
        for j in credit_jobs:
            credit_list.append({
                'job_number'    : j.job_number,
                'title'         : j.title,
                'estimated_cost': str(j.estimated_cost or 0),
                'customer_name' : j.customer.full_name if j.customer else '—',
            })

        # ── Sheet meta ────────────────────────────────────────────
        meta = {
            'sheet_id'  : sheet.pk,
            'date'      : sheet.date.isoformat(),
            'status'    : sheet.status,
            'branch'    : branch.name,
            'branch_code': branch.code,
            'opened_at' : sheet.opened_at.isoformat() if sheet.opened_at else None,
            'opened_by' : sheet.opened_by.full_name if sheet.opened_by else 'System',
            'is_public_holiday'  : sheet.is_public_holiday,
            'public_holiday_name': sheet.public_holiday_name,
        }

        # ── Branch cashiers (for float staging even with no activity) ─
        from apps.accounts.models import CustomUser
        branch_cashiers = list(
            CustomUser.objects.filter(
                branch    = branch,
                role__name = 'CASHIER',
                is_active = True,
            ).values('id', 'first_name', 'last_name')
        )
        branch_cashiers_list = [
            {
                'cashier_id'  : c['id'],
                'cashier_name': f"{c['first_name']} {c['last_name']}".strip(),
            }
            for c in branch_cashiers
        ]

        return Response({
            'meta'            : meta,
            'revenue'         : revenue,
            'jobs'            : jobs_summary,
            'cashier_activity': cashier_activity,
            'float_opened'    : float_opened,
            'petty_cash'      : petty_cash_list,
            'credit_sales'    : credit_list,
            'branch_cashiers' : branch_cashiers_list,
        })

# ─────────────────────────────────────────────────────────────────────────────
# Invoices
# ─────────────────────────────────────────────────────────────────────────────

class InvoiceListView(generics.ListAPIView):
    """
    GET /api/v1/finance/invoices/
    Returns all invoices for the requesting user's branch.
    """
    serializer_class   = InvoiceSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
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

        return qs


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
        from decimal import Decimal
        from django.utils import timezone
        from apps.jobs.models import Job, JobLineItem, Service
        from apps.jobs.pricing_engine import PricingEngine

        serializer = InvoiceCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        d      = serializer.validated_data
        user   = request.user
        branch = getattr(user, 'branch', None)

        if not branch:
            return Response(
                {'detail': 'No branch assigned.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Resolve job if linked ─────────────────────────────
        job = None
        if d.get('job_id'):
            try:
                job = Job.objects.get(pk=d['job_id'], branch=branch)
            except Job.DoesNotExist:
                return Response(
                    {'detail': 'Job not found.'},
                    status=status.HTTP_404_NOT_FOUND,
                )

        # ── Create invoice ────────────────────────────────────
        invoice = Invoice.objects.create(
            branch           = branch,
            job              = job,
            generated_by     = user,
            invoice_type     = d['invoice_type'],
            due_date         = d.get('due_date'),
            bm_note          = d.get('bm_note', ''),
            bill_to_name     = d['bill_to_name'],
            bill_to_phone    = d.get('bill_to_phone', ''),
            bill_to_email    = d.get('bill_to_email', ''),
            bill_to_company  = d.get('bill_to_company', ''),
            delivery_channel = d['delivery_channel'],
            vat_rate         = d.get('vat_rate', 0),
            status           = Invoice.DRAFT,
        )

        # ── Build line items ──────────────────────────────────
        if job:
            # Pull from job's line items
            job_items = JobLineItem.objects.filter(
                job=job
            ).select_related('service').order_by('position')

            for i, li in enumerate(job_items):
                InvoiceLineItem.objects.create(
                    invoice    = invoice,
                    service    = li.service,
                    label      = li.label or li.service.name,
                    quantity   = li.quantity,
                    pages      = li.pages,
                    sets       = li.sets,
                    is_color   = li.is_color,
                    paper_size = li.paper_size,
                    sides      = li.sides,
                    unit_price = li.unit_price,
                    line_total = li.line_total,
                    position   = i,
                )
        else:
            # Standalone — build from submitted line items
            for i, item in enumerate(d.get('line_items', [])):
                try:
                    svc = Service.objects.get(pk=item['service'])
                except Service.DoesNotExist:
                    continue

                pg       = int(item.get('pages', 1))
                sets     = int(item.get('sets', 1))
                is_color = bool(item.get('is_color', False))

                pricing = PricingEngine.get_price(
                    service  = svc,
                    branch   = branch,
                    quantity = sets,
                    is_color = is_color,
                    pages    = pg,
                )
                line_total  = Decimal(str(pricing.get('total', 0)))
                unit_price  = line_total / (pg * sets) if (pg * sets) > 0 else Decimal('0')

                InvoiceLineItem.objects.create(
                    invoice    = invoice,
                    service    = svc,
                    label      = svc.name,
                    quantity   = sets,
                    pages      = pg,
                    sets       = sets,
                    is_color   = is_color,
                    paper_size = item.get('paper_size', 'A4'),
                    sides      = item.get('sides', 'SINGLE'),
                    unit_price = unit_price,
                    line_total = line_total,
                    position   = i,
                )

        # ── Compute totals ────────────────────────────────────
        invoice.compute_totals()
        invoice.save(update_fields=[
            'subtotal', 'vat_amount', 'total', 'updated_at'
        ])

        # ── Generate PDF ──────────────────────────────────────
        try:
            _generate_invoice_pdf(invoice)
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"PDF generation failed: {e}", exc_info=True)

        # ── Deliver ───────────────────────────────────────────
        _deliver_invoice(invoice)

        return Response(
            InvoiceSerializer(invoice).data,
            status=status.HTTP_201_CREATED,
        )


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


# ─────────────────────────────────────────────────────────────────────────────
# Invoice helpers
# ─────────────────────────────────────────────────────────────────────────────

def _generate_invoice_pdf(invoice):
    """Generate a PDF for the invoice and save path to invoice.pdf_path."""
    import os
    from django.conf import settings
    from django.utils import timezone

    media_root  = getattr(settings, 'MEDIA_ROOT', 'media')
    invoices_dir = os.path.join(media_root, 'invoices')
    os.makedirs(invoices_dir, exist_ok=True)

    output_path = os.path.join(
        invoices_dir, f"{invoice.invoice_number}.pdf"
    )

    # Build PDF using reportlab
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle,
        Paragraph, Spacer, HRFlowable,
    )
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT

    doc    = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=20*mm, leftMargin=20*mm,
        topMargin=20*mm,   bottomMargin=20*mm,
    )
    styles = getSampleStyleSheet()
    W      = A4[0] - 40*mm

    # ── Custom styles ─────────────────────────────────────────
    h1 = ParagraphStyle('h1', fontSize=20, fontName='Helvetica-Bold',
                         textColor=colors.HexColor('#111111'))
    h2 = ParagraphStyle('h2', fontSize=11, fontName='Helvetica-Bold',
                         textColor=colors.HexColor('#111111'))
    sm = ParagraphStyle('sm', fontSize=9,  fontName='Helvetica',
                         textColor=colors.HexColor('#666666'))
    sm_bold = ParagraphStyle('smb', fontSize=9, fontName='Helvetica-Bold',
                              textColor=colors.HexColor('#111111'))
    right = ParagraphStyle('right', fontSize=9, fontName='Helvetica',
                            alignment=TA_RIGHT,
                            textColor=colors.HexColor('#666666'))
    right_bold = ParagraphStyle('rightb', fontSize=11, fontName='Helvetica-Bold',
                                 alignment=TA_RIGHT,
                                 textColor=colors.HexColor('#111111'))

    def fmt(n):
        return f"GHS {float(n or 0):,.2f}"

    story = []

    # ── Header ────────────────────────────────────────────────
    header_data = [[
        Paragraph('Farhat Printing Press', h1),
        Paragraph(
            f"<b>{invoice.invoice_type} INVOICE</b>",
            ParagraphStyle('inv', fontSize=14, fontName='Helvetica-Bold',
                           alignment=TA_RIGHT,
                           textColor=colors.HexColor(
                               '#1a4fd6' if invoice.invoice_type == 'PROFORMA'
                               else '#1a7a4a'
                           ))
        ),
    ]]
    header_table = Table(header_data, colWidths=[W*0.6, W*0.4])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
    ]))
    story.append(header_table)

    # Branch info
    branch = invoice.branch
    story.append(Paragraph(
        f"{branch.name} &nbsp;·&nbsp; {branch.code}",
        sm
    ))
    story.append(Spacer(1, 6*mm))
    story.append(HRFlowable(width=W, thickness=1,
                             color=colors.HexColor('#eeeeee')))
    story.append(Spacer(1, 6*mm))

    # ── Invoice meta + Bill To ────────────────────────────────
    issued  = invoice.issue_date.strftime('%d %b %Y') if invoice.issue_date else '—'
    due     = invoice.due_date.strftime('%d %b %Y')   if invoice.due_date   else '—'

    bill_lines = [invoice.bill_to_name]
    if invoice.bill_to_company: bill_lines.append(invoice.bill_to_company)
    if invoice.bill_to_phone:   bill_lines.append(invoice.bill_to_phone)
    if invoice.bill_to_email:   bill_lines.append(invoice.bill_to_email)

    meta_data = [[
        [
            Paragraph('BILL TO', ParagraphStyle('lbl', fontSize=8,
                fontName='Helvetica-Bold',
                textColor=colors.HexColor('#aaaaaa'),
                spaceAfter=3)),
            *[Paragraph(line, sm_bold if i == 0 else sm)
              for i, line in enumerate(bill_lines)],
        ],
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
    meta_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 8*mm))

    # Job ref if linked
    if invoice.job:
        story.append(Paragraph(
            f"Job Reference: <b>{invoice.job.job_number}</b>",
            sm
        ))
        story.append(Spacer(1, 4*mm))

    # ── Line items table ──────────────────────────────────────
    table_data = [[
        Paragraph('SERVICE', ParagraphStyle('th', fontSize=8,
            fontName='Helvetica-Bold',
            textColor=colors.HexColor('#aaaaaa'))),
        Paragraph('QTY', ParagraphStyle('th2', fontSize=8,
            fontName='Helvetica-Bold',
            textColor=colors.HexColor('#aaaaaa'),
            alignment=TA_CENTER)),
        Paragraph('UNIT PRICE', ParagraphStyle('th3', fontSize=8,
            fontName='Helvetica-Bold',
            textColor=colors.HexColor('#aaaaaa'),
            alignment=TA_RIGHT)),
        Paragraph('TOTAL', ParagraphStyle('th4', fontSize=8,
            fontName='Helvetica-Bold',
            textColor=colors.HexColor('#aaaaaa'),
            alignment=TA_RIGHT)),
    ]]

    for li in invoice.line_items.all():
        detail = f"{li.paper_size} · {'Colour' if li.is_color else 'B&W'}"
        if li.pages > 1:
            detail += f" · {li.pages}pp × {li.sets} sets"
        table_data.append([
            [
                Paragraph(li.label, sm_bold),
                Paragraph(detail, sm),
            ],
            Paragraph(str(li.quantity), ParagraphStyle('c', fontSize=9,
                fontName='Helvetica', alignment=TA_CENTER,
                textColor=colors.HexColor('#444444'))),
            Paragraph(fmt(li.unit_price), ParagraphStyle('r', fontSize=9,
                fontName='Helvetica', alignment=TA_RIGHT,
                textColor=colors.HexColor('#444444'))),
            Paragraph(fmt(li.line_total), ParagraphStyle('rb', fontSize=9,
                fontName='Helvetica-Bold', alignment=TA_RIGHT,
                textColor=colors.HexColor('#111111'))),
        ])

    col_w = [W*0.5, W*0.1, W*0.2, W*0.2]
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

    # ── Totals ────────────────────────────────────────────────
    totals_data = []
    totals_data.append([
        Paragraph('Subtotal', sm),
        Paragraph(fmt(invoice.subtotal), right),
    ])
    if invoice.vat_rate:
        totals_data.append([
            Paragraph(f'VAT ({invoice.vat_rate}%)', sm),
            Paragraph(fmt(invoice.vat_amount), right),
        ])
    totals_data.append([
        Paragraph('<b>Total</b>', ParagraphStyle('tb', fontSize=11,
            fontName='Helvetica-Bold',
            textColor=colors.HexColor('#111111'))),
        Paragraph(f'<b>{fmt(invoice.total)}</b>',
            ParagraphStyle('trb', fontSize=11,
            fontName='Helvetica-Bold', alignment=TA_RIGHT,
            textColor=colors.HexColor('#111111'))),
    ])

    totals_table = Table(totals_data, colWidths=[W*0.75, W*0.25])
    totals_table.setStyle(TableStyle([
        ('ALIGN',         (1,0), (1,-1), 'RIGHT'),
        ('LINEABOVE',     (0,-1), (-1,-1), 1, colors.HexColor('#eeeeee')),
        ('TOPPADDING',    (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(totals_table)

    # ── Status badge ──────────────────────────────────────────
    story.append(Spacer(1, 6*mm))
    status_color = {
        'DRAFT': '#888888', 'SENT': '#3355cc',
        'VIEWED': '#cc8800', 'PAID': '#1a7a4a',
    }.get(invoice.status, '#888888')

    story.append(Paragraph(
        f'<font color="{status_color}"><b>STATUS: {invoice.status}</b></font>',
        ParagraphStyle('st', fontSize=10, fontName='Helvetica-Bold')
    ))

    # ── BM note ───────────────────────────────────────────────
    if invoice.bm_note:
        story.append(Spacer(1, 6*mm))
        story.append(HRFlowable(width=W, thickness=0.5,
                                 color=colors.HexColor('#eeeeee')))
        story.append(Spacer(1, 4*mm))
        story.append(Paragraph(invoice.bm_note, sm))

    # ── Footer ────────────────────────────────────────────────
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

    # Save path
    invoice.pdf_path = output_path
    invoice.save(update_fields=['pdf_path', 'updated_at'])


def _deliver_invoice(invoice):
    """Send invoice via its delivery channel. Marks status as SENT."""
    from django.utils import timezone

    # Mark as SENT — PDF is available for download via the PDF endpoint
    # WhatsApp/Email delivery stubs until integrations are wired
    invoice.status  = Invoice.SENT
    invoice.sent_at = timezone.now()
    invoice.save(update_fields=['status', 'sent_at', 'updated_at'])


def _send_invoice_whatsapp(invoice):
    """Stub — wire to WhatsApp Business API when ready."""
    # TODO: integrate with WhatsApp Business API
    # For now just log and return True for testing
    print(f"[WhatsApp] Sending invoice {invoice.invoice_number} to {invoice.bill_to_phone}")
    return True

def _generate_weekly_pdf(report):
    """
    Generate the weekly filing PDF.
    Page 1: Cover page matching Farhat brand template
    Page 2+: Filing content — revenue, jobs, cashiers, notes
    """
    import os
    import calendar
    from django.conf import settings
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle,
        Paragraph, Spacer, HRFlowable, PageBreak,
    )
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT
    from reportlab.platypus.flowables import Flowable

    media_root  = getattr(settings, 'MEDIA_ROOT', 'media')
    weekly_dir  = os.path.join(media_root, 'weekly')
    os.makedirs(weekly_dir, exist_ok=True)

    output_path = os.path.join(
        weekly_dir,
        f"weekly_{report.branch.code}_W{report.week_number}_{report.year}.pdf"
    )

    branch = report.branch
    W, H   = A4  # 595 x 842 pts

    # ── Colors ────────────────────────────────────────────────────────────
    FARHAT_RED   = colors.HexColor('#E31E24')
    FARHAT_GOLD  = colors.HexColor('#F5A623')
    WHITE        = colors.white
    BLACK        = colors.HexColor('#111111')
    GREY         = colors.HexColor('#666666')
    LIGHT_GREY   = colors.HexColor('#f5f5f5')
    BORDER_GREY  = colors.HexColor('#e0e0e0')

    # ── Styles ────────────────────────────────────────────────────────────
    def fmt(n):
        return f"GHS {float(n or 0):,.2f}"

    # ── Custom cover page flowable ─────────────────────────────────────────
    class CoverPage(Flowable):
        def __init__(self, width, height, branch, report):
            Flowable.__init__(self)
            self.width   = width
            self.height  = height
            self.branch  = branch
            self.report  = report

        def draw(self):
            c = self.canv
            W = self.width
            H = self.height

            # White background
            c.setFillColor(colors.white)
            c.rect(0, 0, W, H, fill=1, stroke=0)

            # Red center panel (60% width, full height)
            panel_x = W * 0.20
            panel_w = W * 0.60
            c.setFillColor(FARHAT_RED)
            c.rect(panel_x, 0, panel_w, H, fill=1, stroke=0)

            # ── Logo area (white bird silhouette approximation) ──────────
            # Draw a simple white circle as logo placeholder
            logo_cx = panel_x + panel_w / 2
            logo_cy = H * 0.72
            logo_r  = 28

            c.setFillColor(WHITE)
            c.circle(logo_cx, logo_cy, logo_r, fill=1, stroke=0)

            # Draw stylized F in the circle
            c.setFillColor(FARHAT_RED)
            c.setFont('Helvetica-Bold', 22)
            c.drawCentredString(logo_cx, logo_cy - 8, 'F')

            # ── Branch name ───────────────────────────────────────────────
            branch_name = self.branch.name.upper()
            # Split into two lines if long
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

            # ── Week / Month / Year ───────────────────────────────────────
            month_name = calendar.month_name[self.report.date_from.month].upper()
            week_str   = f"WEEK {self.report.week_number},  {month_name},  {self.report.year}"

            c.setFillColor(FARHAT_GOLD)
            c.setFont('Helvetica-Bold', 14)
            c.drawCentredString(logo_cx, H * 0.36, week_str)

            # ── Contact info ──────────────────────────────────────────────
            email = self.branch.email or 'info@farhatprintingpress.com'
            phone = self.branch.phone or self.branch.whatsapp_number or '+233 556244194'

            c.setFillColor(WHITE)
            c.setFont('Helvetica-Bold', 11)
            c.drawCentredString(logo_cx, H * 0.26, email)
            c.drawCentredString(logo_cx, H * 0.21, phone)

            # ── Footer ────────────────────────────────────────────────────
            c.setFillColor(FARHAT_GOLD)
            c.setFont('Helvetica-Bold', 7)
            c.drawCentredString(logo_cx, H * 0.07, 'MANDATORY WEEKLY FILING')
            c.drawCentredString(logo_cx, H * 0.055, 'STRICTLY CONFIDENTIAL')

            c.setFillColor(WHITE)
            c.setFont('Helvetica', 7)
            c.drawCentredString(logo_cx, H * 0.035, 'Property of Farhat Printing Press')

    # ── Build document ────────────────────────────────────────────────────
    from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate

    doc = BaseDocTemplate(
        output_path,
        pagesize     = A4,
        rightMargin  = 20*mm,
        leftMargin   = 20*mm,
        topMargin    = 20*mm,
        bottomMargin = 20*mm,
    )

    # Cover page template — full bleed, no margins
    cover_frame   = Frame(0, 0, W, H, leftPadding=0, rightPadding=0,
                          topPadding=0, bottomPadding=0, id='cover')
    content_frame = Frame(20*mm, 20*mm, W - 40*mm, H - 40*mm, id='normal')

    doc.addPageTemplates([
        PageTemplate(id='Cover',  frames=cover_frame),
        PageTemplate(id='Later',  frames=content_frame),
    ])

    styles = getSampleStyleSheet()
    from reportlab.platypus import NextPageTemplate

    story  = []

    # Page 1 — Cover (full bleed)
    story.append(NextPageTemplate('Later'))
    story.append(CoverPage(W, H, branch, report))
    story.append(PageBreak())

    # ── Content page styles ───────────────────────────────────────────────
    CW = A4[0] - 40*mm  # content width

    h1_style = ParagraphStyle('h1', fontSize=18, fontName='Helvetica-Bold',
                               textColor=BLACK, spaceAfter=4)
    h2_style = ParagraphStyle('h2', fontSize=11, fontName='Helvetica-Bold',
                               textColor=BLACK, spaceAfter=4)
    label_style = ParagraphStyle('lbl', fontSize=8, fontName='Helvetica-Bold',
                                  textColor=GREY, letterSpacing=0.5,
                                  spaceAfter=8)
    body_style  = ParagraphStyle('body', fontSize=9, fontName='Helvetica',
                                  textColor=GREY)
    right_style = ParagraphStyle('right', fontSize=9, fontName='Helvetica',
                                  alignment=TA_RIGHT, textColor=BLACK)
    right_bold  = ParagraphStyle('rightb', fontSize=10, fontName='Helvetica-Bold',
                                  alignment=TA_RIGHT, textColor=BLACK)

    # ── Page 2 header ─────────────────────────────────────────────────────
    month_name = calendar.month_name[report.date_from.month]
    story.append(Paragraph(f"{branch.name}", h1_style))
    story.append(Paragraph(
        f"Weekly Filing — Week {report.week_number}, {month_name} {report.year}  "
        f"({report.date_from.strftime('%d %b')} – {report.date_to.strftime('%d %b %Y')})",
        label_style
    ))
    story.append(HRFlowable(width=CW, thickness=2, color=FARHAT_RED))
    story.append(Spacer(1, 6*mm))

    # ── Revenue summary ───────────────────────────────────────────────────
    story.append(Paragraph('REVENUE SUMMARY', label_style))

    rev_data = [
        ['Method', 'Amount (GHS)', '% of Total'],
        ['Cash',   f"{float(report.total_cash):,.2f}",
         f"{float(report.total_cash)/float(report.total_collected)*100:.1f}%" if report.total_collected else '0%'],
        ['Mobile Money', f"{float(report.total_momo):,.2f}",
         f"{float(report.total_momo)/float(report.total_collected)*100:.1f}%" if report.total_collected else '0%'],
        ['POS',    f"{float(report.total_pos):,.2f}",
         f"{float(report.total_pos)/float(report.total_collected)*100:.1f}%" if report.total_collected else '0%'],
        ['TOTAL COLLECTED', f"{float(report.total_collected):,.2f}", '100%'],
        ['Petty Cash Out', f"({float(report.total_petty_cash_out):,.2f})", ''],
        ['Net Cash in Till', f"{float(report.net_cash_in_till):,.2f}", ''],
    ]

    rev_table = Table(rev_data, colWidths=[CW*0.45, CW*0.30, CW*0.25])
    rev_table.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,0),  colors.HexColor('#f5f5f5')),
        ('FONTNAME',      (0,0), (-1,0),  'Helvetica-Bold'),
        ('FONTSIZE',      (0,0), (-1,-1), 9),
        ('FONTNAME',      (0,4), (-1,4),  'Helvetica-Bold'),
        ('BACKGROUND',    (0,4), (-1,4),  colors.HexColor('#fff0f0')),
        ('TEXTCOLOR',     (0,4), (-1,4),  FARHAT_RED),
        ('ALIGN',         (1,0), (-1,-1), 'RIGHT'),
        ('GRID',          (0,0), (-1,-1), 0.5, BORDER_GREY),
        ('TOPPADDING',    (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING',   (0,0), (-1,-1), 8),
        ('RIGHTPADDING',  (0,0), (-1,-1), 8),
    ]))
    story.append(rev_table)
    story.append(Spacer(1, 6*mm))

    # ── Daily breakdown ───────────────────────────────────────────────────
    story.append(Paragraph('DAILY BREAKDOWN', label_style))

    day_headers = ['Date', 'Day', 'Status', 'Cash', 'MoMo', 'POS', 'Total', 'Jobs']
    day_data    = [day_headers]

    sheets = report.daily_sheets.all().order_by('date')
    for sheet in sheets:
        day_name = sheet.date.strftime('%A')
        total    = float(sheet.total_cash + sheet.total_momo + sheet.total_pos)
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
            ('BACKGROUND',    (0,0), (-1,0),  colors.HexColor('#f5f5f5')),
            ('FONTNAME',      (0,0), (-1,0),  'Helvetica-Bold'),
            ('FONTSIZE',      (0,0), (-1,-1), 8),
            ('ALIGN',         (3,0), (-1,-1), 'RIGHT'),
            ('GRID',          (0,0), (-1,-1), 0.5, BORDER_GREY),
            ('TOPPADDING',    (0,0), (-1,-1), 5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
            ('LEFTPADDING',   (0,0), (-1,-1), 6),
            ('RIGHTPADDING',  (0,0), (-1,-1), 6),
            ('ROWBACKGROUNDS',(0,1), (-1,-1), [colors.white, colors.HexColor('#fafafa')]),
        ]))
        story.append(day_table)
    else:
        story.append(Paragraph('No daily sheets linked.', body_style))

    story.append(Spacer(1, 6*mm))

    # ── Jobs summary ──────────────────────────────────────────────────────
    story.append(Paragraph('JOBS SUMMARY', label_style))

    jobs_data = [
        ['Metric', 'Count'],
        ['Total Jobs Created',   str(report.total_jobs_created)],
        ['Completed',            str(report.total_jobs_complete)],
        ['Cancelled',            str(report.total_jobs_cancelled)],
        ['Carry Forward (Unpaid)', str(report.carry_forward_count)],
    ]

    jobs_table = Table(jobs_data, colWidths=[CW*0.65, CW*0.35])
    jobs_table.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,0),  colors.HexColor('#f5f5f5')),
        ('FONTNAME',      (0,0), (-1,0),  'Helvetica-Bold'),
        ('FONTSIZE',      (0,0), (-1,-1), 9),
        ('ALIGN',         (1,0), (1,-1),  'RIGHT'),
        ('GRID',          (0,0), (-1,-1), 0.5, BORDER_GREY),
        ('TOPPADDING',    (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING',   (0,0), (-1,-1), 8),
        ('RIGHTPADDING',  (0,0), (-1,-1), 8),
        ('ROWBACKGROUNDS',(0,1), (-1,-1), [colors.white, colors.HexColor('#fafafa')]),
    ]))
    story.append(jobs_table)
    story.append(Spacer(1, 6*mm))

    # ── Inventory ─────────────────────────────────────────────────────────
    story.append(Paragraph('INVENTORY', label_style))
    snapshot = report.inventory_snapshot
    items    = snapshot.get('items', []) if snapshot else []
    low_stock = snapshot.get('low_stock', []) if snapshot else []

    if items:
        inv_headers = ['Consumable', 'Category', 'Unit', 'Opening', 'Received', 'Consumed', 'Closing', 'Status']
        inv_data    = [inv_headers]
        for item in items:
            is_low  = item.get('is_low', False)
            status_label = 'LOW' if is_low else 'OK'
            inv_data.append([
                item.get('consumable', '—'),
                item.get('category', '—'),
                item.get('unit', '—'),
                str(item.get('opening', 0)),
                str(item.get('received', 0)),
                str(item.get('consumed', 0)),
                str(item.get('closing', 0)),
                status_label,
            ])

        col_w = [CW*0.28, CW*0.12, CW*0.07, CW*0.08, CW*0.09, CW*0.09, CW*0.08, CW*0.09]
        inv_table = Table(inv_data, colWidths=col_w, repeatRows=1)

        # Build row styles — highlight low stock rows red
        row_styles = [
            ('BACKGROUND',    (0,0), (-1,0),  colors.HexColor('#f5f5f5')),
            ('FONTNAME',      (0,0), (-1,0),  'Helvetica-Bold'),
            ('FONTSIZE',      (0,0), (-1,-1), 8),
            ('ALIGN',         (3,0), (-1,-1), 'RIGHT'),
            ('GRID',          (0,0), (-1,-1), 0.5, BORDER_GREY),
            ('TOPPADDING',    (0,0), (-1,-1), 5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
            ('LEFTPADDING',   (0,0), (-1,-1), 6),
            ('RIGHTPADDING',  (0,0), (-1,-1), 6),
            ('ROWBACKGROUNDS',(0,1), (-1,-1), [colors.white, colors.HexColor('#fafafa')]),
        ]
        for i, item in enumerate(items, start=1):
            if item.get('is_low', False):
                row_styles.append(('TEXTCOLOR', (7,i), (7,i), FARHAT_RED))
                row_styles.append(('FONTNAME',  (7,i), (7,i), 'Helvetica-Bold'))

        inv_table.setStyle(TableStyle(row_styles))
        story.append(inv_table)

        if low_stock:
            story.append(Spacer(1, 3*mm))
            story.append(Paragraph(
                f"<font color='#E31E24'><b>Low stock alert:</b></font> {', '.join(low_stock)}",
                body_style
            ))
    else:
        inv_placeholder = Table(
            [['No inventory data available for this period.']],
            colWidths=[CW]
        )
        inv_placeholder.setStyle(TableStyle([
            ('BACKGROUND',    (0,0), (-1,-1), colors.HexColor('#fffbec')),
            ('FONTNAME',      (0,0), (-1,-1), 'Helvetica'),
            ('FONTSIZE',      (0,0), (-1,-1), 9),
            ('TEXTCOLOR',     (0,0), (-1,-1), colors.HexColor('#7a5c00')),
            ('BOX',           (0,0), (-1,-1), 0.5, colors.HexColor('#f0d878')),
            ('TOPPADDING',    (0,0), (-1,-1), 10),
            ('BOTTOMPADDING', (0,0), (-1,-1), 10),
            ('LEFTPADDING',   (0,0), (-1,-1), 12),
        ]))
        story.append(inv_placeholder)

    story.append(Spacer(1, 6*mm))

    # ── BM Notes ──────────────────────────────────────────────────────────
    story.append(Paragraph('BRANCH MANAGER NOTES', label_style))
    notes_text = report.bm_notes or '—'
    notes_table = Table([[notes_text]], colWidths=[CW])
    notes_table.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,-1), colors.HexColor('#f9f9f9')),
        ('FONTNAME',      (0,0), (-1,-1), 'Helvetica'),
        ('FONTSIZE',      (0,0), (-1,-1), 9),
        ('TEXTCOLOR',     (0,0), (-1,-1), BLACK),
        ('BOX',           (0,0), (-1,-1), 0.5, BORDER_GREY),
        ('TOPPADDING',    (0,0), (-1,-1), 10),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
        ('LEFTPADDING',   (0,0), (-1,-1), 12),
    ]))
    story.append(notes_table)
    story.append(Spacer(1, 8*mm))

    # ── Sign-off block ────────────────────────────────────────────────────
    story.append(HRFlowable(width=CW, thickness=1, color=BORDER_GREY))
    story.append(Spacer(1, 4*mm))

    submitted_by = report.submitted_by.full_name if report.submitted_by else '—'
    submitted_at = (
        report.submitted_at.strftime('%d %b %Y, %I:%M %p')
        if report.submitted_at else '—'
    )

    signoff_data = [
        ['Filed by', submitted_by, 'Date', submitted_at],
        ['Branch',   branch.name,  'Week', f"W{report.week_number}/{report.year}"],
    ]
    signoff_table = Table(signoff_data, colWidths=[CW*0.15, CW*0.35, CW*0.15, CW*0.35])
    signoff_table.setStyle(TableStyle([
        ('FONTNAME',      (0,0), (0,-1),  'Helvetica-Bold'),
        ('FONTNAME',      (2,0), (2,-1),  'Helvetica-Bold'),
        ('FONTSIZE',      (0,0), (-1,-1), 9),
        ('TEXTCOLOR',     (0,0), (0,-1),  GREY),
        ('TEXTCOLOR',     (2,0), (2,-1),  GREY),
        ('TOPPADDING',    (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
    ]))
    story.append(signoff_table)
    story.append(Spacer(1, 4*mm))
    story.append(Paragraph(
        'This document is the property of Farhat Printing Press. '
        'Strictly confidential — for internal use only.',
        ParagraphStyle('ft', fontSize=7, fontName='Helvetica',
                       textColor=GREY, alignment=TA_CENTER)
    ))

    doc.build(story)

    # Save path
    report.pdf_path = output_path
    report.save(update_fields=['pdf_path', 'updated_at'])

def _send_invoice_email(invoice):
    """Send invoice PDF via Django email."""
    if not invoice.bill_to_email:
        return False

    try:
        from django.core.mail import EmailMessage
        import os

        subject = f"Invoice {invoice.invoice_number} — Farhat Printing Press"
        body    = invoice.bm_note or (
            f"Dear {invoice.bill_to_name},\n\n"
            f"Please find attached your {invoice.get_invoice_type_display()} "
            f"from Farhat Printing Press.\n\n"
            f"Invoice No: {invoice.invoice_number}\n"
            f"Amount: GHS {invoice.total}\n\n"
            f"Thank you for your business."
        )

        email = EmailMessage(
            subject = subject,
            body    = body,
            to      = [invoice.bill_to_email],
        )

        if invoice.pdf_path and os.path.exists(invoice.pdf_path):
            email.attach_file(invoice.pdf_path)

        email.send()
        return True

    except Exception as e:
        print(f"[Email] Failed to send invoice {invoice.invoice_number}: {e}")
        return False

# ─────────────────────────────────────────────────────────────────────────────
# Weekly Report
# ─────────────────────────────────────────────────────────────────────────────

class WeeklyReportListView(generics.ListAPIView):
    """
    GET /api/v1/finance/weekly/
    Returns weekly reports for the requesting user's branch.
    """
    serializer_class   = WeeklyReportListSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs   = WeeklyReport.objects.select_related(
            'branch', 'submitted_by'
        ).prefetch_related('daily_sheets')
        if hasattr(user, 'branch') and user.branch:
            qs = qs.filter(branch=user.branch)
        return qs


class WeeklyReportDetailView(generics.RetrieveAPIView):
    """
    GET /api/v1/finance/weekly/<id>/
    Full weekly report detail including daily sheets.
    """
    serializer_class   = WeeklyReportDetailSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs   = WeeklyReport.objects.select_related(
            'branch', 'submitted_by'
        ).prefetch_related('daily_sheets')
        if hasattr(user, 'branch') and user.branch:
            qs = qs.filter(branch=user.branch)
        return qs


class WeeklyReportPrepareView(APIView):
    """
    POST /api/v1/finance/weekly/prepare/
    Creates or refreshes a DRAFT weekly report for the current week.
    Aggregates all closed daily sheets Mon–Sat into the report.
    Can be called multiple times — safe to re-prepare a DRAFT.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from django.utils import timezone
        from datetime import timedelta
        from apps.jobs.models import Job

        user   = request.user
        branch = getattr(user, 'branch', None)
        if not branch:
            return Response(
                {'detail': 'No branch assigned.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Resolve current week Mon–Sat ──────────────────────────────
        today     = timezone.localdate()
        monday    = today - timedelta(days=today.weekday())  # weekday() 0=Mon
        saturday  = monday + timedelta(days=5)

        # ISO week number
        week_number = today.isocalendar()[1]
        year        = today.isocalendar()[0]

        # ── Get or create the report ──────────────────────────────────
        report, created = WeeklyReport.objects.get_or_create(
            branch      = branch,
            week_number = week_number,
            year        = year,
            defaults    = {
                'date_from' : monday,
                'date_to'   : saturday,
                'status'    : WeeklyReport.Status.DRAFT,
            }
        )

        if report.is_locked:
            return Response(
                {'detail': 'This weekly report is already locked.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Find all sheets for this week ─────────────────────────────
        sheets = DailySalesSheet.objects.filter(
            branch = branch,
            date__range = [monday, saturday],
        )

        # ── Link sheets ───────────────────────────────────────────────
        report.daily_sheets.set(sheets)

        # ── Aggregate from closed sheets only ─────────────────────────
        from django.db.models import Sum

        closed_sheets = sheets.exclude(status=DailySalesSheet.Status.OPEN)

        report.total_cash           = closed_sheets.aggregate(t=Sum('total_cash'))['t']           or 0
        report.total_momo           = closed_sheets.aggregate(t=Sum('total_momo'))['t']           or 0
        report.total_pos            = closed_sheets.aggregate(t=Sum('total_pos'))['t']            or 0
        report.total_petty_cash_out = closed_sheets.aggregate(t=Sum('total_petty_cash_out'))['t'] or 0
        report.total_credit_issued  = closed_sheets.aggregate(t=Sum('total_credit_issued'))['t']  or 0
        report.net_cash_in_till     = closed_sheets.aggregate(t=Sum('net_cash_in_till'))['t']     or 0
        report.total_jobs_created   = closed_sheets.aggregate(t=Sum('total_jobs_created'))['t']   or 0

        # Job level counts from actual jobs
        week_jobs = Job.objects.filter(
            branch      = branch,
            created_at__date__range = [monday, saturday],
        )
        report.total_jobs_complete  = week_jobs.filter(status='COMPLETE').count()
        report.total_jobs_cancelled = week_jobs.filter(status='CANCELLED').count()
        report.carry_forward_count  = week_jobs.filter(status='PENDING_PAYMENT').count()

        report.date_from = monday
        report.date_to   = saturday

        # ── Inventory snapshot ────────────────────────────────────────
        try:
            from apps.inventory.inventory_engine import InventoryEngine
            report.inventory_snapshot = InventoryEngine(branch).generate_weekly_snapshot(
                date_from = monday,
                date_to   = saturday,
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Inventory snapshot failed: {e}", exc_info=True)

        report.save()

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
    All sheets must be closed before submission is allowed.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        from django.utils import timezone

        try:
            report = WeeklyReport.objects.prefetch_related(
                'daily_sheets'
            ).get(pk=pk, branch=request.user.branch)
        except WeeklyReport.DoesNotExist:
            return Response({'detail': 'Report not found.'}, status=status.HTTP_404_NOT_FOUND)

        if report.is_locked:
            return Response({'detail': 'Already submitted.'}, status=status.HTTP_400_BAD_REQUEST)

        # Submit only allowed on Saturday after Saturday's sheet is closed
        today = timezone.localdate()
        if today.weekday() != 5:  # 5 = Saturday
            return Response(
                {'detail': 'Weekly report can only be submitted on Saturday after closing.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not report.daily_sheets.exists():
            return Response(
                {'detail': 'No daily sheets linked. Prepare the report first.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not report.all_sheets_closed:
            open_sheets = report.daily_sheets.filter(
                status=DailySalesSheet.Status.OPEN
            ).values_list('date', flat=True)
            dates = ', '.join(str(d) for d in open_sheets)
            return Response(
                {'detail': f'Cannot submit — sheets still open: {dates}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Re-aggregate to make sure figures are fresh ───────────────
        from django.db.models import Sum
        from apps.jobs.models import Job

        closed_sheets = report.daily_sheets.exclude(status=DailySalesSheet.Status.OPEN)
        report.total_cash           = closed_sheets.aggregate(t=Sum('total_cash'))['t']           or 0
        report.total_momo           = closed_sheets.aggregate(t=Sum('total_momo'))['t']           or 0
        report.total_pos            = closed_sheets.aggregate(t=Sum('total_pos'))['t']            or 0
        report.total_petty_cash_out = closed_sheets.aggregate(t=Sum('total_petty_cash_out'))['t'] or 0
        report.total_credit_issued  = closed_sheets.aggregate(t=Sum('total_credit_issued'))['t']  or 0
        report.net_cash_in_till     = closed_sheets.aggregate(t=Sum('net_cash_in_till'))['t']     or 0
        report.total_jobs_created   = closed_sheets.aggregate(t=Sum('total_jobs_created'))['t']   or 0

        week_jobs = Job.objects.filter(
            branch                  = report.branch,
            created_at__date__range = [report.date_from, report.date_to],
        )
        report.total_jobs_complete  = week_jobs.filter(status='COMPLETE').count()
        report.total_jobs_cancelled = week_jobs.filter(status='CANCELLED').count()
        report.carry_forward_count  = week_jobs.filter(status='PENDING_PAYMENT').count()
        # ── Refresh inventory snapshot on submit ──────────────────────
        try:
            from apps.inventory.inventory_engine import InventoryEngine
            report.inventory_snapshot = InventoryEngine(report.branch).generate_weekly_snapshot(
                date_from = report.date_from,
                date_to   = report.date_to,
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Inventory snapshot failed: {e}", exc_info=True)

        # ── Lock the report ───────────────────────────────────────────
        report.status       = WeeklyReport.Status.LOCKED
        report.submitted_by = request.user
        report.submitted_at = timezone.now()
        report.save()

        # ── Generate PDF ──────────────────────────────────────────────
        try:
            _generate_weekly_pdf(report)
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Weekly PDF generation failed: {e}", exc_info=True)

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
            return Response({'detail': 'Report not found.'}, status=404)

        if not report.pdf_path:
            try:
                _generate_weekly_pdf(report)
            except Exception as e:
                return Response({'detail': f'PDF generation failed: {e}'}, status=500)

        import os
        if not os.path.exists(report.pdf_path):
            try:
                _generate_weekly_pdf(report)
            except Exception as e:
                return Response({'detail': f'PDF generation failed: {e}'}, status=500)

        from django.http import FileResponse
        response = FileResponse(
            open(report.pdf_path, 'rb'),
            content_type='application/pdf',
        )
        response['Content-Disposition'] = (
            f'attachment; filename="weekly_{report.branch.code}_W{report.week_number}_{report.year}.pdf"'
        )
        return response
