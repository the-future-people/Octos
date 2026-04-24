from rest_framework import generics, filters, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from django.db import models

from apps.jobs.models import Job, JobFile, Service, PricingRule
from apps.jobs.status_engine import JobStatusEngine
from apps.jobs.routing_engine import RoutingEngine
from apps.jobs.pricing_engine import PricingEngine
from apps.organization.models import Branch

from .serializers import (
    JobListSerializer, JobDetailSerializer, JobCreateSerializer,
    JobTransitionSerializer, JobRouteSerializer, JobFileUploadSerializer,
    ServiceSerializer, PricingRuleSerializer, CashierPaymentSerializer,
)


# ─────────────────────────────────────────────────────────────────────────────
# Jobs
# ─────────────────────────────────────────────────────────────────────────────

class JobListView(generics.ListAPIView):
    serializer_class   = JobListSerializer
    permission_classes = [IsAuthenticated]
    filter_backends    = [filters.SearchFilter]
    search_fields = ['job_number', 'title', 'customer__contact_name', 'customer__contact_phone']

    def get_queryset(self):
        user = self.request.user
        qs   = Job.objects.select_related(
            'branch', 'assigned_to', 'customer', 'intake_by'
        )

        if hasattr(user, 'branch') and user.branch:
            qs = qs.filter(branch=user.branch)

        branch_id    = self.request.query_params.get('branch')
        job_type     = self.request.query_params.get('job_type')
        status_param = self.request.query_params.get('status')

        if branch_id:
            qs = qs.filter(branch_id=branch_id)
        if job_type:
            qs = qs.filter(job_type=job_type)
        if status_param:
            qs = qs.filter(status=status_param)

        daily_sheet = self.request.query_params.get('daily_sheet')
        if daily_sheet:
            qs = qs.filter(daily_sheet_id=daily_sheet)

        customer = self.request.query_params.get('customer')
        if customer:
            qs = qs.filter(customer_id=customer)

        intake_by = self.request.query_params.get('intake_by')
        if intake_by == 'me':
            qs = qs.filter(intake_by=user)
        elif intake_by:
            qs = qs.filter(intake_by_id=intake_by)

        period = self.request.query_params.get('period')
        if period:
            from django.utils import timezone
            from datetime import timedelta
            now = timezone.now()
            since = {
                'day':   now.replace(hour=0, minute=0, second=0, microsecond=0),
                'week':  (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0),
                'month': now.replace(day=1, hour=0, minute=0, second=0, microsecond=0),
                'year':  now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0),
            }.get(period)
            if since:
                qs = qs.filter(created_at__gte=since)

        return qs


class JobDetailView(generics.RetrieveAPIView):
    serializer_class   = JobDetailSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs   = Job.objects.select_related(
            'branch', 'assigned_to', 'customer', 'intake_by'
        ).prefetch_related('files', 'status_logs')

        if hasattr(user, 'branch') and user.branch:
            qs = qs.filter(branch=user.branch)

        return qs


class JobCreateView(generics.CreateAPIView):
    serializer_class   = JobCreateSerializer
    permission_classes = [IsAuthenticated]


class JobTransitionView(APIView):
    """
    POST /api/v1/jobs/<id>/transition/
    Body: { to_status, notes? }
    Advances job through its lifecycle using the status engine.
    Role-based guards are enforced inside the engine.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            job = Job.objects.get(pk=pk)
        except Job.DoesNotExist:
            return Response(
                {'detail': 'Job not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = JobTransitionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            result = JobStatusEngine.advance(
                job       = job,
                to_status = serializer.validated_data['to_status'],
                actor     = request.user,
                notes     = serializer.validated_data.get('notes', ''),
            )
            return Response(result)
        except PermissionError as e:
            return Response({'detail': str(e)}, status=status.HTTP_403_FORBIDDEN)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)


# ─────────────────────────────────────────────────────────────────────────────
# Cashier
# ─────────────────────────────────────────────────────────────────────────────

class CashierQueueView(generics.ListAPIView):
    """
    GET /api/v1/jobs/cashier/queue/
    Returns all PENDING_PAYMENT jobs for the cashier's branch.
    Ordered oldest-first so the cashier works the queue in sequence.
    """
    serializer_class   = JobListSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs   = Job.objects.select_related(
            'branch', 'customer', 'intake_by'
        ).filter(status=Job.PENDING_PAYMENT)

        if hasattr(user, 'branch') and user.branch:
            qs = qs.filter(branch=user.branch)

        return qs.order_by('created_at')  # FIFO

class CashierSummaryView(APIView):
    """
    GET /api/v1/jobs/cashier/summary/
    Returns today's payment totals per method for the cashier's branch.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.utils import timezone
        from apps.jobs.selectors.revenue_selectors import get_cashier_summary

        user = request.user
        if not hasattr(user, 'branch') or not user.branch:
            return Response(
                {'detail': 'User has no branch assigned.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = get_cashier_summary(user.branch, timezone.localdate())
        return Response(data)
       
class CashierConfirmPaymentView(APIView):
    """
    POST /api/v1/jobs/<id>/cashier/confirm/
    Body: { deposit_percentage: 70|100, notes? }

    Cashier selects the deposit tier, system calculates amount_paid,
    then advances the job to PAID via the status engine.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        from apps.jobs.services.cashier_service import confirm_payment

        try:
            job = Job.objects.get(pk=pk, status=Job.PENDING_PAYMENT)
        except Job.DoesNotExist:
            return Response(
                {'detail': 'Job not found or not awaiting payment.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = CashierPaymentSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            result = confirm_payment(job, serializer.validated_data, request.user)
        except (ValueError, PermissionError) as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(result)
class JobFileUploadView(APIView):
    """
    POST /api/v1/jobs/<id>/files/
    Upload a file attachment to a job.
    """
    permission_classes = [IsAuthenticated]
    parser_classes     = [MultiPartParser, FormParser]

    def post(self, request, pk):
        try:
            job = Job.objects.get(pk=pk)
        except Job.DoesNotExist:
            return Response(
                {'detail': 'Job not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = JobFileUploadSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        job_file = JobFile.objects.create(
            job=job,
            uploaded_by=request.user,
            **serializer.validated_data,
        )

        from .serializers import JobFileSerializer
        return Response(
            JobFileSerializer(job_file).data,
            status=status.HTTP_201_CREATED,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Routing
# ─────────────────────────────────────────────────────────────────────────────

class JobRouteSuggestView(APIView):
    """GET /api/v1/jobs/<id>/route/suggest/?service=<id>"""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            job = Job.objects.select_related('branch').get(pk=pk)
        except Job.DoesNotExist:
            return Response({'detail': 'Job not found.'}, status=status.HTTP_404_NOT_FOUND)

        service_id = request.query_params.get('service')
        if not service_id:
            return Response({'detail': 'service query param is required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            service = Service.objects.get(pk=service_id)
        except Service.DoesNotExist:
            return Response({'detail': 'Service not found.'}, status=status.HTTP_404_NOT_FOUND)

        result = RoutingEngine.suggest(job=job, service=service)

        if result['success']:
            result['suggestions'] = [
                {
                    'branch_id'           : s['branch_id'],
                    'branch_name'         : s['branch_name'],
                    'branch_code'         : s['branch_code'],
                    'score'               : s['score'],
                    'ring'                : s['ring'],
                    'is_hq'               : s['is_hq'],
                    'load_percentage'     : s['load_percentage'],
                    'is_superheavy_route' : s['is_superheavy_route'],
                }
                for s in result['suggestions']
            ]
            if result['top_suggestion']:
                top = result['top_suggestion']
                result['top_suggestion'] = {
                    'branch_id'   : top['branch_id'],
                    'branch_name' : top['branch_name'],
                    'score'       : top['score'],
                    'is_hq'       : top['is_hq'],
                }

        return Response(result)


class JobRouteConfirmView(APIView):
    """POST /api/v1/jobs/<id>/route/confirm/"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            job = Job.objects.get(pk=pk)
        except Job.DoesNotExist:
            return Response({'detail': 'Job not found.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = JobRouteSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            branch = Branch.objects.get(pk=serializer.validated_data['branch_id'])
        except Branch.DoesNotExist:
            return Response({'detail': 'Branch not found.'}, status=status.HTTP_404_NOT_FOUND)

        job.assigned_to    = branch
        job.is_routed      = True
        job.routing_reason = serializer.validated_data.get('notes', '')
        job.save(update_fields=['assigned_to', 'is_routed', 'routing_reason', 'updated_at'])

        return Response({
            'success'      : True,
            'job_number'   : job.job_number,
            'routed_to'    : branch.name,
            'routed_to_id' : branch.id,
        })


# ─────────────────────────────────────────────────────────────────────────────
# Services & Pricing
# ─────────────────────────────────────────────────────────────────────────────

class ServiceListView(generics.ListAPIView):
    serializer_class   = ServiceSerializer
    permission_classes = [IsAuthenticated]
    pagination_class   = None
    def get_queryset(self):
        qs       = Service.objects.filter(is_active=True)
        category = self.request.query_params.get('category')
        if category:
            qs = qs.filter(category=category)
        return qs

class ServiceCreateView(APIView):
    """
    POST /api/v1/jobs/services/create/
    Create a new service with pricing rule and optional consumable mappings.
    """
    permission_classes = [IsAuthenticated]
    parser_classes     = [MultiPartParser, FormParser]

    def post(self, request):
        from apps.jobs.api.serializers import ServiceCreateSerializer
        from apps.jobs.services.job_service import create_service

        serializer = ServiceCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        branch = getattr(request.user, 'branch', None)
        service = create_service(
            user              = request.user,
            branch            = branch,
            validated_data    = serializer.validated_data,
            raw_mappings_json = request.data.get('consumable_mappings'),
        )

        return Response(ServiceSerializer(service).data, status=status.HTTP_201_CREATED)
class PricingRuleListView(generics.ListAPIView):
    serializer_class   = PricingRuleSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs         = PricingRule.objects.select_related('service', 'branch').filter(is_active=True)
        branch_id  = self.request.query_params.get('branch')
        service_id = self.request.query_params.get('service')
        if branch_id:
            qs = qs.filter(branch_id=branch_id)
        if service_id:
            qs = qs.filter(service_id=service_id)
        return qs


class PriceCalculateView(APIView):
    """
    GET /api/v1/jobs/price/calculate/?service=&branch=&quantity=&pages=&is_color=
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        service_id = request.query_params.get('service')
        branch_id  = request.query_params.get('branch')

        if not service_id or not branch_id:
            return Response(
                {'detail': 'service and branch are required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            quantity = int(request.query_params.get('quantity', 1))
            pages    = int(request.query_params.get('pages', 1))
        except ValueError:
            return Response(
                {'detail': 'quantity and pages must be integers.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        is_color = request.query_params.get('is_color', 'false').lower() == 'true'

        # Conditional pricing params
        condition_params = {}
        ring_size   = request.query_params.get('ring_size')
        output_mode = request.query_params.get('output_mode')
        if ring_size:
            condition_params['ring_size'] = int(ring_size)
        if output_mode:
            condition_params['output_mode'] = output_mode

        try:
            service = Service.objects.get(pk=service_id)
            branch  = Branch.objects.get(pk=branch_id)
        except Service.DoesNotExist:
            return Response({'detail': 'Service not found.'}, status=status.HTTP_404_NOT_FOUND)
        except Branch.DoesNotExist:
            return Response({'detail': 'Branch not found.'}, status=status.HTTP_404_NOT_FOUND)

        result = PricingEngine.get_price(
            service          = service,
            branch           = branch,
            quantity         = quantity,
            is_color         = is_color,
            pages            = pages,
            condition_params = condition_params,
        )
        return Response(result)

class SaveDraftView(APIView):
    """
    POST /api/v1/jobs/drafts/save/
    Auto-saves an in-progress job as a DRAFT.
    Called when attendant closes the NJ modal with items in cart.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from apps.jobs.services.job_service import save_draft

        branch = getattr(request.user, 'branch', None)
        if not branch:
            return Response({'detail': 'User has no branch assigned.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            result = save_draft(request.user, branch, request.data)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(result, status=status.HTTP_201_CREATED)
class LateJobView(APIView):
    """
    POST /api/v1/jobs/late/
    BM creates a post-closing job after branch closing time.
    Requires a mandatory reason. Job goes directly to cashier queue.
    Logged with BM name, timestamp and reason for HQ audit.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from apps.jobs.services.job_service import create_late_job
        from apps.jobs.api.serializers import JobListSerializer

        branch = getattr(request.user, 'branch', None)
        if not branch:
            return Response({'detail': 'No branch assigned.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            job = create_late_job(request.user, branch, request.data)
        except PermissionError as e:
            return Response({'detail': str(e)}, status=status.HTTP_403_FORBIDDEN)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            JobListSerializer(job, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )
class DraftListView(generics.ListAPIView):
    """
    GET /api/v1/jobs/drafts/
    Returns all active DRAFT jobs for the user's branch.
    Ordered oldest first so attendants work the queue.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.jobs.models import Job
        from django.utils import timezone

        branch = getattr(request.user, 'branch', None)
        if not branch:
            return Response([])

        drafts = Job.objects.filter(
            branch           = branch,
            status           = Job.DRAFT,
            draft_expires_at__gt = timezone.now(),
        ).prefetch_related('line_items__service').order_by('created_at')

        data = []
        for j in drafts:
            items = j.line_items.all()
            data.append({
                'id'            : j.id,
                'job_number'    : j.job_number,
                'title'         : j.title,
                'estimated_cost': str(j.estimated_cost or 0),
                'created_at'    : j.created_at.isoformat(),
                'expires_at'    : j.draft_expires_at.isoformat(),
                'intake_by'     : j.intake_by.full_name if j.intake_by else '—',
                'line_items'    : [
                    {
                        'service'   : item.service_id,
                        'service_name': item.service.name,
                        'pages'     : item.pages,
                        'sets'      : item.sets,
                        'quantity'  : item.quantity,
                        'is_color'  : item.is_color,
                        'paper_size': item.paper_size,
                        'sides'     : item.sides,
                        'unit_price': str(item.unit_price),
                        'line_total': str(item.line_total),
                        'label'     : item.label,
                    }
                    for item in items
                ],
            })

        return Response(data)


class DiscardDraftView(APIView):
    """
    POST /api/v1/jobs/drafts/<pk>/discard/
    Marks a draft as ABANDONED — kept for analytics, not resumable.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        from apps.jobs.models import Job
        from django.utils import timezone

        try:
            job = Job.objects.get(pk=pk, status=Job.DRAFT)
        except Job.DoesNotExist:
            return Response(
                {'detail': 'Draft not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if job.branch != getattr(request.user, 'branch', None):
            return Response(
                {'detail': 'Access denied.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        job.status       = Job.CANCELLED
        job.abandoned_at = timezone.now()
        job.save(update_fields=['status', 'abandoned_at'])

        return Response({'detail': 'Draft discarded.'})

class ServicePerformanceView(APIView):
    """
    GET /api/v1/jobs/reports/services/?period=day|week|month|year
    Returns service performance stats for the branch.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.db.models import Sum, Count
        from django.utils import timezone
        from datetime import timedelta
        from apps.jobs.models import JobLineItem

        branch = getattr(request.user, 'branch', None)
        if not branch:
            return Response({'detail': 'No branch assigned.'}, status=400)

        period = request.query_params.get('period', 'month')
        now    = timezone.now()

        if period == 'day':
            since = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == 'week':
            since = now - timedelta(days=now.weekday())
            since = since.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == 'year':
            since = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        else:  # month
            since = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        qs = JobLineItem.objects.filter(
            job__branch=branch,
            job__status='COMPLETE',
            job__created_at__gte=since,
        ).values(
            'service__name'
        ).annotate(
            job_count  = Count('job', distinct=True),
            revenue    = Sum('line_total'),
        ).order_by('-revenue')

        total_revenue = sum(float(r['revenue'] or 0) for r in qs)

        data = [
            {
                'service'   : r['service__name'],
                'job_count' : r['job_count'],
                'revenue'   : str(r['revenue'] or 0),
                'percentage': round(float(r['revenue'] or 0) / total_revenue * 100, 1)
                              if total_revenue else 0,
            }
            for r in qs
        ]

        return Response({'period': period, 'since': since.isoformat(), 'services': data})

class JobStatsView(APIView):
    """
    GET /api/v1/jobs/stats/?daily_sheet=<id>
    Returns aggregated branch stats + personal attendant stats.
    Personal stats require the requesting user to have jobs on the sheet.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.jobs.selectors.stats_selectors import get_branch_stats, get_personal_stats

        user   = request.user
        branch = getattr(user, 'branch', None)
        if not branch:
            return Response({'detail': 'No branch assigned.'}, status=400)

        sheet_id = request.query_params.get('daily_sheet')

        branch_stats = get_branch_stats(branch, sheet_id)

        personal = {}
        try:
            personal = get_personal_stats(user, branch, sheet_id)
        except Exception:
            pass  # never let personal stats break branch stats

        return Response({**branch_stats, 'personal': personal})

class JobHistoryView(APIView):
    """
    GET /api/v1/jobs/history/
    
    Aggregated job history at any drill-down level.
    
    Params:
      level = year | month | week | day
      year  = 2026
      month = 3  (1-12)
      week  = 1  (week number within month, 1-5)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.jobs.selectors.job_selectors import (
            get_year_level, get_month_level, get_week_level, get_day_level,
        )

        user   = request.user
        branch = getattr(user, 'branch', None)
        if not branch:
            return Response({'detail': 'No branch assigned.'}, status=400)

        level = request.query_params.get('level', 'year')
        year  = request.query_params.get('year')
        month = request.query_params.get('month')
        week  = request.query_params.get('week')

        year  = int(year)  if year  else None
        month = int(month) if month else None
        week  = int(week)  if week  else None

        base_qs = Job.objects.filter(branch=branch)

        if level == 'year':
            return Response(get_year_level(base_qs, branch))
        elif level == 'month' and year:
            return Response(get_month_level(base_qs, branch, year))
        elif level == 'week' and year and month:
            return Response(get_week_level(base_qs, branch, year, month))
        elif level == 'day' and year and month and week is not None:
            data = get_day_level(base_qs, branch, year, month, week)
            if data is None:
                return Response({'detail': 'Week not found.'}, status=400)
            return Response(data)
        else:
            return Response({'detail': 'Invalid parameters.'}, status=400)
