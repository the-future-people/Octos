from rest_framework import generics, filters, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser

from apps.jobs.models import Job, JobFile, Service, PricingRule
from apps.jobs.status_engine import JobStatusEngine
from apps.jobs.routing_engine import RoutingEngine
from apps.jobs.pricing_engine import PricingEngine
from apps.organization.models import Branch

from .serializers import (
    JobListSerializer, JobDetailSerializer, JobCreateSerializer,
    JobTransitionSerializer, JobRouteSerializer, JobFileUploadSerializer,
    ServiceSerializer, PricingRuleSerializer,
)


class JobListView(generics.ListAPIView):
    serializer_class   = JobListSerializer
    permission_classes = [IsAuthenticated]
    filter_backends    = [filters.SearchFilter]
    search_fields      = ['job_number', 'title']

    def get_queryset(self):
        user = self.request.user
        qs   = Job.objects.select_related(
            'branch', 'assigned_to', 'customer', 'intake_by'
        )

        # Scope to user's branch by default
        if hasattr(user, 'branch') and user.branch:
            qs = qs.filter(branch=user.branch)

        # Optional filter overrides
        branch_id    = self.request.query_params.get('branch')
        job_type     = self.request.query_params.get('job_type')
        status_param = self.request.query_params.get('status')
        is_routed    = self.request.query_params.get('is_routed')

        if branch_id:
            qs = qs.filter(branch_id=branch_id)
        if job_type:
            qs = qs.filter(job_type=job_type)
        if status_param:
            qs = qs.filter(status=status_param)
        if is_routed is not None:
            qs = qs.filter(is_routed=is_routed.lower() == 'true')

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
                job=job,
                to_status=serializer.validated_data['to_status'],
                actor=request.user,
                notes=serializer.validated_data.get('notes', ''),
            )
            return Response(result)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class JobFileUploadView(APIView):
    """
    POST /api/v1/jobs/<id>/files/
    Upload a file attachment to a job (artwork, sample, final, reference).
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


class JobRouteSuggestView(APIView):
    """
    GET /api/v1/jobs/<id>/route/suggest/?service=<id>
    Returns ranked branch suggestions for routing this job.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            job = Job.objects.select_related('branch').get(pk=pk)
        except Job.DoesNotExist:
            return Response(
                {'detail': 'Job not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        service_id = request.query_params.get('service')
        if not service_id:
            return Response(
                {'detail': 'service query param is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            service = Service.objects.get(pk=service_id)
        except Service.DoesNotExist:
            return Response(
                {'detail': 'Service not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        result = RoutingEngine.suggest(job=job, service=service)

        # Serialize branch objects out of the result
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
    """
    POST /api/v1/jobs/<id>/route/confirm/
    Body: { branch_id, notes? }
    Confirms routing this job to the specified branch.
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

        serializer = JobRouteSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            branch = Branch.objects.get(pk=serializer.validated_data['branch_id'])
        except Branch.DoesNotExist:
            return Response(
                {'detail': 'Branch not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

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


class ServiceListView(generics.ListAPIView):
    serializer_class   = ServiceSerializer
    permission_classes = [IsAuthenticated]

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
    GET /api/v1/jobs/price/calculate/?service=<id>&branch=<id>&quantity=1&pages=1&is_color=false
    Returns a full price breakdown before creating a job.
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
            service=service,
            branch=branch,
            quantity=quantity,
            is_color=is_color,
            pages=pages,
        )
        return Response(result)