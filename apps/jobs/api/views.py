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

                # ── Issue receipt ─────────────────────────────────────────
            receipt_number = None
            try:
                    from apps.finance.receipt_engine import ReceiptEngine
                    from apps.finance.models import DailySalesSheet

                    daily_sheet = DailySalesSheet.objects.filter(
                        branch = job.branch,
                        status = DailySalesSheet.Status.OPEN,
                    ).order_by('-date').first()

                    if daily_sheet:
                        engine  = ReceiptEngine(job.branch)
                        receipt = engine.issue(
                            job               = job,
                            cashier           = request.user,
                            daily_sheet       = daily_sheet,
                            payment_method    = serializer.validated_data.get('payment_method', 'CASH'),
                            amount_paid       = amount_paid,
                            balance_due       = job.balance_due or 0,
                            momo_reference    = serializer.validated_data.get('momo_reference', ''),
                            pos_approval_code = serializer.validated_data.get('pos_approval_code', ''),
                            customer_phone    = serializer.validated_data.get('customer_phone', ''),
                            company_name      = serializer.validated_data.get('company_name', ''),
                        )
                        receipt_number          = receipt.receipt_number
                        result['receipt_id']    = receipt.id
                        result['receipt_number'] = receipt_number
                    else:
                        result['receipt_number'] = None
                        result['receipt_id']     = None
            except Exception as e:
                    import logging
                    logging.getLogger(__name__).error(f"ReceiptEngine failed: {e}", exc_info=True)
                    result['receipt_number'] = None
                    result['receipt_id']     = None

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
        from django.db.models import Sum, Count, Q
        from django.utils import timezone
        from datetime import date, timedelta
        import calendar

        user   = request.user
        branch = getattr(user, 'branch', None)
        if not branch:
            return Response({'detail': 'No branch assigned.'}, status=400)

        level = request.query_params.get('level', 'year')
        year  = request.query_params.get('year')
        month = request.query_params.get('month')
        week  = request.query_params.get('week')

        # Convert to int
        year  = int(year)  if year  else None
        month = int(month) if month else None
        week  = int(week)  if week  else None

        base_qs = Job.objects.filter(branch=branch)

        if level == 'year':
            return self._year_level(request, base_qs, branch)
        elif level == 'month' and year:
            return self._month_level(request, base_qs, branch, year)
        elif level == 'week' and year and month:
            return self._week_level(request, base_qs, branch, year, month)
        elif level == 'day' and year and month and week is not None:
            return self._day_level(request, base_qs, branch, year, month, week)
        else:
            return Response({'detail': 'Invalid parameters.'}, status=400)

    # ── Helpers ───────────────────────────────────────────────

    def _agg(self, qs):
        """Aggregate a queryset into KPI numbers."""
        from django.db.models import Sum, Count
        result = qs.aggregate(
            total    = Count('id'),
            complete = Count('id', filter=models.Q(status='COMPLETE')),
            pending  = Count('id', filter=models.Q(status='PENDING_PAYMENT')),
            revenue  = Sum('amount_paid', filter=models.Q(status='COMPLETE')),
        )
        total    = result['total']    or 0
        complete = result['complete'] or 0
        pending  = result['pending']  or 0
        revenue  = float(result['revenue'] or 0)
        rate     = round(complete / total * 100, 1) if total else 0
        return {
            'total'    : total,
            'complete' : complete,
            'pending'  : pending,
            'revenue'  : revenue,
            'rate'     : rate,
        }

    def _pct_change(self, current, previous):
        """Compute % change between two values."""
        if not previous:
            return None
        change = round((current - previous) / previous * 100, 1)
        return f"+{change}%" if change >= 0 else f"{change}%"

    def _week_ranges(self, year, month):
        """Return list of (week_num, start_date, end_date) for Mon-Sat weeks in a month."""
        import calendar
        from datetime import date, timedelta
        
        first_day = date(year, month, 1)
        last_day  = date(year, month, calendar.monthrange(year, month)[1])
        
        weeks = []
        current = first_day
        # Move to Monday
        while current.weekday() != 0:
            current -= timedelta(days=1)
        
        week_num = 1
        while current <= last_day:
            week_start = current
            week_end   = min(current + timedelta(days=5), last_day)  # Mon-Sat
            if week_end >= first_day:  # Only include if overlaps with month
                weeks.append((week_num, week_start, week_end))
                week_num += 1
            current += timedelta(days=7)
        
        return weeks

    # ── Year level ────────────────────────────────────────────

    def _year_level(self, request, base_qs, branch):
        from django.db.models.functions import TruncYear, TruncMonth
        from django.db.models import Sum, Count
        from datetime import date

        # Get all years with data
        years_qs = base_qs.dates('created_at', 'year')
        current_year = date.today().year

        # Also always include current year
        year_set = set(d.year for d in years_qs) | {current_year}
        years    = sorted(year_set, reverse=True)

        # Current year KPIs
        cur_qs  = base_qs.filter(created_at__year=current_year)
        prev_qs = base_qs.filter(created_at__year=current_year - 1)
        cur     = self._agg(cur_qs)
        prev    = self._agg(prev_qs)

        kpis = {
            'total'  : { 'value': cur['total'],   'change': self._pct_change(cur['total'],   prev['total'])   },
            'revenue': { 'value': cur['revenue'],  'change': self._pct_change(cur['revenue'], prev['revenue']) },
            'pending': { 'value': cur['pending'],  'change': self._pct_change(cur['pending'], prev['pending']) },
            'rate'   : { 'value': cur['rate'],     'change': self._pct_change(cur['rate'],    prev['rate'])    },
        }

        # Trend — jobs per month for current year
        trend_labels  = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
        trend_jobs    = []
        trend_revenue = []
        for m in range(1, 13):
            mqs = cur_qs.filter(created_at__month=m)
            agg = self._agg(mqs)
            trend_jobs.append(agg['total'])
            trend_revenue.append(agg['revenue'])

        # Bar — jobs per year
        bar_labels = [str(y) for y in sorted(years)]
        bar_data   = []
        for y in sorted(years):
            bar_data.append(self._agg(base_qs.filter(created_at__year=y))['total'])

        # Heatmap — jobs per week of current year (52 weeks)
        from datetime import date, timedelta
        heatmap = []
        start = date(current_year, 1, 1)
        for w in range(52):
            week_start = start + timedelta(weeks=w)
            week_end   = week_start + timedelta(days=6)
            count = cur_qs.filter(
                created_at__date__gte=week_start,
                created_at__date__lte=week_end,
            ).count()
            heatmap.append({'week': w + 1, 'count': count})

        # Drill-down items
        items = []
        for y in years:
            agg = self._agg(base_qs.filter(created_at__year=y))
            items.append({
                'label'   : str(y),
                'year'    : y,
                'total'   : agg['total'],
                'revenue' : agg['revenue'],
                'rate'    : agg['rate'],
            })

        return Response({
            'level'  : 'year',
            'kpis'   : kpis,
            'trend'  : { 'labels': trend_labels, 'jobs': trend_jobs, 'revenue': trend_revenue },
            'bar'    : { 'labels': bar_labels,   'data': bar_data },
            'heatmap': heatmap,
            'items'  : items,
        })

    # ── Month level ───────────────────────────────────────────

    def _month_level(self, request, base_qs, branch, year):
        import calendar
        from datetime import date

        month_names = ['Jan','Feb','Mar','Apr','May','Jun',
                       'Jul','Aug','Sep','Oct','Nov','Dec']

        cur_qs  = base_qs.filter(created_at__year=year)
        prev_qs = base_qs.filter(created_at__year=year - 1)
        cur     = self._agg(cur_qs)
        prev    = self._agg(prev_qs)

        kpis = {
            'total'  : { 'value': cur['total'],   'change': self._pct_change(cur['total'],   prev['total'])   },
            'revenue': { 'value': cur['revenue'],  'change': self._pct_change(cur['revenue'], prev['revenue']) },
            'pending': { 'value': cur['pending'],  'change': self._pct_change(cur['pending'], prev['pending']) },
            'rate'   : { 'value': cur['rate'],     'change': self._pct_change(cur['rate'],    prev['rate'])    },
        }

        # Trend — jobs per month
        trend_labels  = month_names
        trend_jobs    = []
        trend_revenue = []
        for m in range(1, 13):
            mqs = cur_qs.filter(created_at__month=m)
            agg = self._agg(mqs)
            trend_jobs.append(agg['total'])
            trend_revenue.append(agg['revenue'])

        # Bar — same as trend
        bar_labels = month_names
        bar_data   = trend_jobs[:]

        # Heatmap — jobs per day of year
        from datetime import date, timedelta
        heatmap = []
        start = date(year, 1, 1)
        for w in range(52):
            week_start = start + timedelta(weeks=w)
            week_end   = week_start + timedelta(days=6)
            count = cur_qs.filter(
                created_at__date__gte=week_start,
                created_at__date__lte=week_end,
            ).count()
            heatmap.append({'week': w + 1, 'count': count})

        # Drill-down items — months
        items = []
        for m in range(1, 13):
            mqs = cur_qs.filter(created_at__month=m)
            agg = self._agg(mqs)
            if agg['total'] > 0 or m <= date.today().month:
                items.append({
                    'label'  : month_names[m - 1],
                    'year'   : year,
                    'month'  : m,
                    'total'  : agg['total'],
                    'revenue': agg['revenue'],
                    'rate'   : agg['rate'],
                })

        return Response({
            'level'  : 'month',
            'year'   : year,
            'kpis'   : kpis,
            'trend'  : { 'labels': trend_labels, 'jobs': trend_jobs, 'revenue': trend_revenue },
            'bar'    : { 'labels': bar_labels,   'data': bar_data },
            'heatmap': heatmap,
            'items'  : items,
        })

    # ── Week level ────────────────────────────────────────────

    def _week_level(self, request, base_qs, branch, year, month):
        import calendar
        from datetime import date

        month_names = ['January','February','March','April','May','June',
                       'July','August','September','October','November','December']

        cur_qs  = base_qs.filter(created_at__year=year, created_at__month=month)
        prev_month = month - 1 if month > 1 else 12
        prev_year  = year if month > 1 else year - 1
        prev_qs = base_qs.filter(created_at__year=prev_year, created_at__month=prev_month)
        cur  = self._agg(cur_qs)
        prev = self._agg(prev_qs)

        kpis = {
            'total'  : { 'value': cur['total'],   'change': self._pct_change(cur['total'],   prev['total'])   },
            'revenue': { 'value': cur['revenue'],  'change': self._pct_change(cur['revenue'], prev['revenue']) },
            'pending': { 'value': cur['pending'],  'change': self._pct_change(cur['pending'], prev['pending']) },
            'rate'   : { 'value': cur['rate'],     'change': self._pct_change(cur['rate'],    prev['rate'])    },
        }

        # Get week ranges
        weeks = self._week_ranges(year, month)

        # Trend — jobs per day of month
        days_in_month = calendar.monthrange(year, month)[1]
        trend_labels  = [str(d) for d in range(1, days_in_month + 1)]
        trend_jobs    = []
        trend_revenue = []
        for d in range(1, days_in_month + 1):
            dqs = cur_qs.filter(created_at__day=d)
            agg = self._agg(dqs)
            trend_jobs.append(agg['total'])
            trend_revenue.append(agg['revenue'])

        # Bar — jobs per week
        bar_labels = [f"Week {w[0]}" for w in weeks]
        bar_data   = []
        for _, ws, we in weeks:
            bar_data.append(
                cur_qs.filter(created_at__date__gte=ws, created_at__date__lte=we).count()
            )

        # Heatmap — jobs per day (Mon-Sat grid)
        heatmap = []
        for _, ws, we in weeks:
            week_row = []
            from datetime import timedelta
            current = ws
            while current <= we:
                count = cur_qs.filter(created_at__date=current).count()
                week_row.append({'date': current.isoformat(), 'count': count})
                current += timedelta(days=1)
            heatmap.append(week_row)

        # Drill-down items — weeks
        items = []
        for wnum, ws, we in weeks:
            wqs = cur_qs.filter(created_at__date__gte=ws, created_at__date__lte=we)
            agg = self._agg(wqs)
            items.append({
                'label'     : f"Week {wnum}",
                'week'      : wnum,
                'year'      : year,
                'month'     : month,
                'start'     : ws.isoformat(),
                'end'       : we.isoformat(),
                'total'     : agg['total'],
                'revenue'   : agg['revenue'],
                'rate'      : agg['rate'],
            })

        return Response({
            'level'  : 'week',
            'year'   : year,
            'month'  : month,
            'month_name': month_names[month - 1],
            'kpis'   : kpis,
            'trend'  : { 'labels': trend_labels, 'jobs': trend_jobs, 'revenue': trend_revenue },
            'bar'    : { 'labels': bar_labels,   'data': bar_data },
            'heatmap': heatmap,
            'items'  : items,
        })

    # ── Day level ─────────────────────────────────────────────

    def _day_level(self, request, base_qs, branch, year, month, week):
        from datetime import date, timedelta
        from apps.finance.models import DailySalesSheet

        weeks  = self._week_ranges(year, month)
        # Find the matching week
        target = next((w for w in weeks if w[0] == week), None)
        if not target:
            return Response({'detail': 'Week not found.'}, status=400)

        _, week_start, week_end = target

        cur_qs  = base_qs.filter(
            created_at__date__gte=week_start,
            created_at__date__lte=week_end,
        )
        # Previous week
        prev_start = week_start - timedelta(days=7)
        prev_end   = week_end   - timedelta(days=7)
        prev_qs    = base_qs.filter(
            created_at__date__gte=prev_start,
            created_at__date__lte=prev_end,
        )
        cur  = self._agg(cur_qs)
        prev = self._agg(prev_qs)

        kpis = {
            'total'  : { 'value': cur['total'],   'change': self._pct_change(cur['total'],   prev['total'])   },
            'revenue': { 'value': cur['revenue'],  'change': self._pct_change(cur['revenue'], prev['revenue']) },
            'pending': { 'value': cur['pending'],  'change': self._pct_change(cur['pending'], prev['pending']) },
            'rate'   : { 'value': cur['rate'],     'change': self._pct_change(cur['rate'],    prev['rate'])    },
        }

        # Trend — jobs per hour of day (aggregated across week)
        trend_labels  = [f"{h:02d}:00" for h in range(8, 20)]
        trend_jobs    = [
            cur_qs.filter(created_at__hour=h).count()
            for h in range(8, 20)
        ]
        trend_revenue = [
            float(cur_qs.filter(
                created_at__hour=h, status='COMPLETE'
            ).aggregate(r=models.Sum('amount_paid'))['r'] or 0)
            for h in range(8, 20)
        ]

        # Bar — jobs per day of week
        day_names  = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
        bar_labels = []
        bar_data   = []
        current    = week_start
        while current <= week_end:
            bar_labels.append(current.strftime('%a %d'))
            bar_data.append(cur_qs.filter(created_at__date=current).count())
            current += timedelta(days=1)

        # Heatmap — jobs per hour per day
        heatmap = []
        current = week_start
        while current <= week_end:
            day_row = []
            for h in range(8, 20):
                count = cur_qs.filter(
                    created_at__date=current,
                    created_at__hour=h,
                ).count()
                day_row.append({'hour': h, 'count': count})
            heatmap.append({'date': current.isoformat(), 'hours': day_row})
            current += timedelta(days=1)

        # Drill-down items — days with sheet info
        items = []
        current = week_start
        while current <= week_end:
            dqs = cur_qs.filter(created_at__date=current)
            agg = self._agg(dqs)

            # Get daily sheet for PDF link
            try:
                sheet = DailySalesSheet.objects.get(branch=branch, date=current)
                sheet_id     = sheet.id
                sheet_status = sheet.status
            except DailySalesSheet.DoesNotExist:
                sheet_id     = None
                sheet_status = None

            items.append({
                'date'        : current.isoformat(),
                'label'       : current.strftime('%a %d %b'),
                'total'       : agg['total'],
                'revenue'     : agg['revenue'],
                'complete'    : agg['complete'],
                'pending'     : agg['pending'],
                'rate'        : agg['rate'],
                'sheet_id'    : sheet_id,
                'sheet_status': sheet_status,
            })
            current += timedelta(days=1)

        return Response({
            'level'     : 'day',
            'year'      : year,
            'month'     : month,
            'week'      : week,
            'week_start': week_start.isoformat(),
            'week_end'  : week_end.isoformat(),
            'kpis'      : kpis,
            'trend'     : { 'labels': trend_labels, 'jobs': trend_jobs, 'revenue': trend_revenue },
            'bar'       : { 'labels': bar_labels,   'data': bar_data },
            'heatmap'   : heatmap,
            'items'     : items,
        })