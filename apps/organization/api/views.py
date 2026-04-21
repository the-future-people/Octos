from rest_framework import generics, filters
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.organization.models import Belt, Region, Branch
from .serializers import BeltSerializer, RegionSerializer, BranchSerializer, BranchListSerializer


class BeltListView(generics.ListAPIView):
    queryset = Belt.objects.all()
    serializer_class = BeltSerializer
    permission_classes = [IsAuthenticated]


class RegionListView(generics.ListAPIView):
    queryset = Region.objects.select_related('belt').all()
    serializer_class = RegionSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None
    filterset_fields = ['belt']

    def get_queryset(self):
        qs = super().get_queryset()
        belt_id = self.request.query_params.get('belt')
        if belt_id:
            qs = qs.filter(belt_id=belt_id)
        return qs


class BranchListView(generics.ListAPIView):
    queryset = Branch.objects.select_related('region', 'region__belt').all()
    serializer_class = BranchSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None
    filter_backends = [filters.SearchFilter]
    search_fields = ['name', 'code']

    def get_queryset(self):
        qs = super().get_queryset()
        region_id = self.request.query_params.get('region')
        is_active = self.request.query_params.get('is_active')
        if region_id:
            qs = qs.filter(region_id=region_id)
        if is_active is not None:
            qs = qs.filter(is_active=is_active.lower() == 'true')
        return qs


class BranchDetailView(generics.RetrieveAPIView):
    queryset = Branch.objects.select_related('region', 'region__belt').all()
    serializer_class = BranchSerializer
    permission_classes = [IsAuthenticated]


class BranchDropdownView(generics.ListAPIView):
    """Lightweight endpoint for dropdowns and selects."""
    queryset = Branch.objects.filter(is_active=True).all()
    serializer_class = BranchListSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None


class RegionalDashboardView(APIView):
    """
    GET /api/v1/organization/regional/dashboard/

    Returns cross-branch health snapshot for the requesting
    Regional Manager's region. One call, all branches.

    Each branch card includes:
      - Sheet status (open / closed / none)
      - Jobs today: total, pending, complete, completion rate
      - Staff on shift count
      - Alert flags: quiet branch, stuck queue, unsigned floats
      - 7-day job trend (daily counts)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.db.models import Count, Sum, Q
        from django.utils import timezone
        from datetime import timedelta

        user = request.user

        # ── Resolve region ────────────────────────────────────
        region = getattr(user, 'region', None)
        if not region:
            # Super admin / Belt can pass ?region=<id>
            region_id = request.query_params.get('region')
            if region_id:
                try:
                    region = Region.objects.get(pk=region_id)
                except Region.DoesNotExist:
                    return Response({'detail': 'Region not found.'}, status=404)
            else:
                return Response(
                    {'detail': 'No region assigned to this account.'},
                    status=400,
                )

        branches = Branch.objects.filter(
            region=region, is_active=True
        ).order_by('name')

        today     = timezone.localdate()
        now       = timezone.now()
        week_ago  = today - timedelta(days=6)

        # ── Pull all today's sheets in one query ──────────────
        from apps.finance.models import DailySalesSheet, CashierFloat
        from apps.jobs.models import Job

        sheets = {
            s.branch_id: s
            for s in DailySalesSheet.objects.filter(
                branch__in=branches, date=today
            )
        }

        # ── Pull all today's jobs in one query ────────────────
        today_jobs = (
            Job.objects
            .filter(branch__in=branches, created_at__date=today)
            .values('branch_id', 'status')
            .annotate(cnt=Count('id'))
        )

        # Reshape: { branch_id: { status: count } }
        jobs_by_branch = {}
        for row in today_jobs:
            bid = row['branch_id']
            if bid not in jobs_by_branch:
                jobs_by_branch[bid] = {}
            jobs_by_branch[bid][row['status']] = row['cnt']

        # ── Pull 7-day trend per branch in one query ──────────
        trend_qs = (
            Job.objects
            .filter(
                branch__in=branches,
                created_at__date__gte=week_ago,
                created_at__date__lte=today,
            )
            .values('branch_id', 'created_at__date')
            .annotate(cnt=Count('id'))
        )

        # Reshape: { branch_id: { date: count } }
        trend_by_branch = {}
        for row in trend_qs:
            bid  = row['branch_id']
            date = row['created_at__date']
            if bid not in trend_by_branch:
                trend_by_branch[bid] = {}
            trend_by_branch[bid][date] = row['cnt']

        # ── Pull unsigned floats per branch ───────────────────
        unsigned_floats = set(
            CashierFloat.objects
            .filter(
                cashier__branch__in  = branches,
                daily_sheet__date    = today,
                morning_acknowledged = False,
            )
            .values_list('cashier__branch_id', flat=True)
            .distinct()
        )

        # ── Pull staff clocked in per branch ──────────────────
        from apps.accounts.models import CustomUser
        staff_counts = {
            row['branch_id']: row['cnt']
            for row in (
                CustomUser.objects
                .filter(branch__in=branches, is_clocked_in=True)
                .values('branch_id')
                .annotate(cnt=Count('id'))
            )
        }

        # ── Build response ────────────────────────────────────
        branch_cards = []
        region_totals = {
            'total': 0, 'complete': 0, 'pending': 0, 'alerts': 0,
        }

        for branch in branches:
            sheet      = sheets.get(branch.id)
            job_counts = jobs_by_branch.get(branch.id, {})

            total    = sum(job_counts.values())
            complete = job_counts.get('COMPLETE', 0)
            pending  = job_counts.get('PENDING_PAYMENT', 0)
            rate     = round(complete / total * 100) if total else 0

            # 7-day trend — Mon to today, fill missing days with 0
            trend = []
            for i in range(7):
                d = week_ago + timedelta(days=i)
                trend.append({
                    'date' : d.isoformat(),
                    'day'  : d.strftime('%a'),
                    'count': trend_by_branch.get(branch.id, {}).get(d, 0),
                })

            # ── Alert flags ───────────────────────────────────
            alerts = []

            # Sheet open but no jobs by midday
            if sheet and sheet.status == 'OPEN':
                hour = now.hour
                if hour >= 12 and total == 0:
                    alerts.append({
                        'type'   : 'quiet',
                        'level'  : 'warning',
                        'message': 'No jobs recorded past midday',
                    })

            # Stuck queue — pending jobs older than 2 hours
            stuck = Job.objects.filter(
                branch=branch,
                status='PENDING_PAYMENT',
                created_at__lte=now - timedelta(hours=2),
            ).count()
            if stuck:
                alerts.append({
                    'type'   : 'stuck_queue',
                    'level'  : 'danger',
                    'message': f'{stuck} job{"s" if stuck > 1 else ""} pending over 2 hours',
                })

            # Unsigned floats
            if branch.id in unsigned_floats:
                alerts.append({
                    'type'   : 'unsigned_float',
                    'level'  : 'warning',
                    'message': 'Cashier float unsigned',
                })

            # No sheet today
            if not sheet:
                alerts.append({
                    'type'   : 'no_sheet',
                    'level'  : 'info',
                    'message': 'No sheet opened today',
                })

            region_totals['total']    += total
            region_totals['complete'] += complete
            region_totals['pending']  += pending
            region_totals['alerts']   += len(alerts)

            branch_cards.append({
                'id'           : branch.id,
                'name'         : branch.name,
                'code'         : branch.code,
                'is_hq'        : branch.is_headquarters,
                'is_regional_hq': branch.is_regional_hq,
                'sheet_status' : sheet.status if sheet else None,
                'sheet_id'     : sheet.id     if sheet else None,
                'jobs': {
                    'total'   : total,
                    'complete': complete,
                    'pending' : pending,
                    'rate'    : rate,
                },
                'staff_on_shift': staff_counts.get(branch.id, 0),
                'alerts'        : alerts,
                'trend'         : trend,
            })

        # ── Region-level summary ──────────────────────────────
        region_rate = round(
            region_totals['complete'] / region_totals['total'] * 100
        ) if region_totals['total'] else 0

        return Response({
            'region': {
                'id'      : region.id,
                'name'    : region.name,
                'code'    : region.code,
                'belt'    : region.belt.name if region.belt else None,
            },
            'summary': {
                'branch_count'    : len(branch_cards),
                'total_jobs'      : region_totals['total'],
                'total_complete'  : region_totals['complete'],
                'total_pending'   : region_totals['pending'],
                'completion_rate' : region_rate,
                'total_alerts'    : region_totals['alerts'],
            },
            'branches'    : branch_cards,
            'generated_at': now.isoformat(),
        })