from rest_framework import generics, filters, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser

from apps.communications import models
from apps.jobs.models import Job, JobFile, Service, PricingRule
from apps.jobs.status_engine import JobStatusEngine
from apps.jobs.routing_engine import RoutingEngine
from apps.jobs.pricing_engine import PricingEngine
from apps.organization.models import Branch
from django.db import models

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
    Used to populate the summary strip on page load.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.db.models import Sum, Count
        from django.utils import timezone

        user = request.user
        if not hasattr(user, 'branch') or not user.branch:
            return Response(
                {'detail': 'User has no branch assigned.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        today = timezone.localdate()

        jobs = Job.objects.filter(
            branch       = user.branch,
            status       = Job.COMPLETE,
            updated_at__date = today,
            amount_paid__isnull = False,
        )

        def _total(method):
            result = jobs.filter(payment_method=method).aggregate(
                total = Sum('amount_paid'),
                count = Count('id'),
            )
            return {
                'total': str(result['total'] or 0),
                'count': result['count'] or 0,
            }

        return Response({
            'CASH' : _total('CASH'),
            'MOMO' : _total('MOMO'),
            'POS'  : _total('POS'),
            'total': {
                'total': str(jobs.aggregate(t=Sum('amount_paid'))['t'] or 0),
                'count': jobs.count(),
            },
        })
    
class CashierConfirmPaymentView(APIView):
    """
    POST /api/v1/jobs/<id>/cashier/confirm/
    Body: { deposit_percentage: 70|100, notes? }

    Cashier selects the deposit tier, system calculates amount_paid,
    then advances the job to PAID via the status engine.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
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

            deposit_pct = serializer.validated_data['deposit_percentage']
            notes       = serializer.validated_data.get('notes', '')

            # Calculate amount paid
            if job.estimated_cost:
                amount_paid = (job.estimated_cost * deposit_pct) / 100
            else:
                amount_paid = None

            # Persist deposit info on the job
            # Persist deposit and payment info on the job
            job.deposit_percentage = deposit_pct
            job.amount_paid        = amount_paid
            job.payment_method     = serializer.validated_data.get('payment_method', 'CASH')
            job.momo_reference     = serializer.validated_data.get('momo_reference', '')
            job.pos_approval_code  = serializer.validated_data.get('pos_approval_code', '')
            job.cash_tendered      = serializer.validated_data.get('cash_tendered')
            job.change_given       = serializer.validated_data.get('change_given')
            job.save(update_fields=[
                'deposit_percentage', 'amount_paid',
                'payment_method', 'momo_reference',
                'pos_approval_code', 'cash_tendered',
                'change_given', 'updated_at',
            ])

            # Advance FSM to COMPLETE — for INSTANT jobs, payment = job done
            try:
                result = JobStatusEngine.advance(
                    job       = job,
                    to_status = Job.COMPLETE,
                    actor     = request.user,
                    notes     = notes or f"Payment confirmed: {deposit_pct}% deposit",
                )
            except (ValueError, PermissionError) as e:
                return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

            result['deposit_percentage'] = deposit_pct
            result['amount_paid']        = str(amount_paid) if amount_paid else None
            result['balance_due']        = str(job.balance_due) if job.balance_due else '0.00'
            result['payment_method']     = serializer.validated_data.get('payment_method', 'CASH')
            result['receipt_number']     = None  # populated after ReceiptEngine is wired in

            return Response(result)


# ─────────────────────────────────────────────────────────────────────────────
# Files
# ─────────────────────────────────────────────────────────────────────────────

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

        try:
            service = Service.objects.get(pk=service_id)
            branch  = Branch.objects.get(pk=branch_id)
        except Service.DoesNotExist:
            return Response({'detail': 'Service not found.'}, status=status.HTTP_404_NOT_FOUND)
        except Branch.DoesNotExist:
            return Response({'detail': 'Branch not found.'}, status=status.HTTP_404_NOT_FOUND)

        result = PricingEngine.get_price(
            service  = service,
            branch   = branch,
            quantity = quantity,
            is_color = is_color,
            pages    = pages,
        )
        return Response(result)

class SaveDraftView(APIView):
    """
    POST /api/v1/jobs/drafts/save/
    Auto-saves an in-progress job as a DRAFT.
    Called when attendant closes the NJ modal with items in cart.
    Creates a new DRAFT job with line items.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from apps.jobs.models import Job, JobLineItem, Service
        from apps.jobs.pricing_engine import PricingEngine
        from apps.finance.sheet_engine import SheetEngine
        from django.utils import timezone
        from datetime import timedelta
        from decimal import Decimal

        user   = request.user
        branch = getattr(user, 'branch', None)
        if not branch:
            return Response(
                {'detail': 'User has no branch assigned.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        line_items_data = request.data.get('line_items', [])
        customer_id     = request.data.get('customer')
        channel         = request.data.get('channel', 'WALK_IN')

        if not line_items_data:
            return Response(
                {'detail': 'No line items to save.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Build title from services
        names = []
        total = Decimal('0.00')
        priced_items = []

        for item in line_items_data:
            try:
                svc = Service.objects.get(pk=item['service'])
            except Service.DoesNotExist:
                continue
            pg       = int(item.get('pages', 1))
            sets     = int(item.get('sets', 1))
            is_color = bool(item.get('is_color', False))
            pricing  = PricingEngine.get_price(
                service  = svc,
                branch   = branch,
                quantity = sets,
                is_color = is_color,
                pages    = pg,
            )
            line_total = Decimal(str(pricing.get('total', 0)))
            unit_price = Decimal(str(pricing.get('base_price', 0)))
            total     += line_total
            names.append(svc.name)
            priced_items.append({
                'service'   : svc,
                'pages'     : pg,
                'sets'      : sets,
                'quantity'  : sets,
                'is_color'  : is_color,
                'paper_size': item.get('paper_size', 'A4'),
                'sides'     : item.get('sides', 'SINGLE'),
                'unit_price': unit_price,
                'line_total': line_total,
                'label'     : svc.name,
            })

        if not priced_items:
            return Response(
                {'detail': 'No valid line items.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if len(names) == 1:
            title = names[0]
        elif len(names) <= 3:
            title = ', '.join(names)
        else:
            title = ', '.join(names[:3]) + f' +{len(names)-3} more'

        # Get or open today's sheet
        sheet, _ = SheetEngine(branch).get_or_open_today()

        now     = timezone.now()
        expires = now + timedelta(days=3)

        # Customer
        from apps.customers.models import CustomerProfile
        customer = None
        if customer_id:
            try:
                customer = CustomerProfile.objects.get(pk=customer_id)
            except CustomerProfile.DoesNotExist:
                pass

        job = Job.objects.create(
            branch           = branch,
            intake_by        = user,
            customer         = customer,
            title            = title,
            job_type         = 'INSTANT',
            status           = Job.DRAFT,
            estimated_cost   = total,
            daily_sheet      = sheet,
            draft_expires_at = expires,
        )

        # Create line items
        for i, item in enumerate(priced_items):
            JobLineItem.objects.create(
                job        = job,
                service    = item['service'],
                quantity   = item['quantity'],
                pages      = item['pages'],
                sets       = item['sets'],
                is_color   = item['is_color'],
                paper_size = item['paper_size'],
                sides      = item['sides'],
                unit_price = item['unit_price'],
                line_total = item['line_total'],
                label      = item['label'],
                position   = i,
            )

        return Response({
            'id'         : job.id,
            'job_number' : job.job_number,
            'title'      : job.title,
            'total'      : str(total),
            'expires_at' : expires.isoformat(),
        }, status=status.HTTP_201_CREATED)


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
    Returns aggregated stats for the sheet — never paginated.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.db.models import Sum, Count

        user   = request.user
        branch = getattr(user, 'branch', None)
        if not branch:
            return Response({'detail': 'No branch assigned.'}, status=400)

        qs = Job.objects.filter(branch=branch)

        sheet_id = request.query_params.get('daily_sheet')
        if sheet_id:
            qs = qs.filter(daily_sheet_id=sheet_id)

        totals = qs.aggregate(
            total        = Count('id'),
            complete     = Count('id', filter=models.Q(status='COMPLETE')),
            in_progress  = Count('id', filter=models.Q(status='IN_PROGRESS')),
            pending      = Count('id', filter=models.Q(status='PENDING_PAYMENT')),
            routed       = Count('id', filter=models.Q(is_routed=True)),
            revenue      = Sum('amount_paid', filter=models.Q(status='COMPLETE')),
        )

        return Response({
            'total'       : totals['total']       or 0,
            'complete'    : totals['complete']     or 0,
            'in_progress' : totals['in_progress']  or 0,
            'pending'     : totals['pending']      or 0,
            'routed'      : totals['routed']       or 0,
            'revenue'     : str(totals['revenue']  or 0),
        })