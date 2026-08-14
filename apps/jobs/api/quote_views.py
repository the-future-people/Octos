"""
Quote API.

Every endpoint here is Branch Manager and above — issuing, revising and
converting are price commitments made on behalf of the branch. The engine
enforces that too; the views fail early so the client gets a clean 403
rather than a 400 from deep inside a transaction.
"""

from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.jobs.models import ProformaInvoice
from apps.jobs.services.quote_engine import QuoteEngine

from .quote_serializers import (
    QuoteCreateSerializer, QuoteReviseSerializer, QuoteConvertSerializer,
    QuoteListSerializer, QuoteDetailSerializer,
)


def _branch_or_400(request):
    branch = getattr(request.user, 'branch', None)
    if not branch:
        return None, Response(
            {'detail': 'No branch assigned.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return branch, None


def _get_quote(pk, branch):
    return ProformaInvoice.objects.select_related(
        'customer', 'issued_by', 'converted_by', 'supersedes', 'job',
    ).filter(pk=pk, branch=branch).first()


class QuoteListView(generics.ListAPIView):
    """
    GET /api/v1/jobs/quotes/?status=ISSUED

    Superseded versions are hidden by default. They are kept as documents
    and reachable through a quote's revision chain, but a list of every
    draft price a customer was ever shown is noise.
    """
    serializer_class   = QuoteListSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        branch = getattr(self.request.user, 'branch', None)
        if not branch:
            return ProformaInvoice.objects.none()

        qs = ProformaInvoice.objects.select_related(
            'customer', 'issued_by', 'job',
        ).filter(branch=branch)

        status_param = self.request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param)
        else:
            qs = qs.exclude(status=ProformaInvoice.Status.SUPERSEDED)

        customer = self.request.query_params.get('customer')
        if customer:
            qs = qs.filter(customer_id=customer)

        return qs.order_by('-created_at')


class QuoteDetailView(generics.RetrieveAPIView):
    serializer_class   = QuoteDetailSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        branch = getattr(self.request.user, 'branch', None)
        if not branch:
            return ProformaInvoice.objects.none()
        return ProformaInvoice.objects.select_related(
            'customer', 'issued_by', 'converted_by', 'supersedes', 'job',
        ).filter(branch=branch)


class QuoteCreateView(APIView):
    """POST /api/v1/jobs/quotes/create/ — creates a DRAFT."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from apps.customers.models import CustomerProfile

        branch, err = _branch_or_400(request)
        if err:
            return err

        serializer = QuoteCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        try:
            customer = CustomerProfile.objects.get(pk=data['customer'])
        except CustomerProfile.DoesNotExist:
            return Response(
                {'detail': 'Customer not found. Quotes go to registered customers only.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            quote = QuoteEngine(branch).create(
                customer       = customer,
                raw_lines      = data['line_items'],
                actor          = request.user,
                notes          = data['notes'],
                contact_person = data['contact_person'],
                contact_phone  = data['contact_phone'],
                contact_email  = data['contact_email'],
            )
        except PermissionError as e:
            return Response({'detail': str(e)}, status=status.HTTP_403_FORBIDDEN)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            QuoteDetailSerializer(quote).data,
            status=status.HTTP_201_CREATED,
        )


class QuoteIssueView(APIView):
    """POST /api/v1/jobs/quotes/<pk>/issue/ — sends it; the clock starts."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        branch, err = _branch_or_400(request)
        if err:
            return err

        quote = _get_quote(pk, branch)
        if not quote:
            return Response({'detail': 'Quote not found.'},
                            status=status.HTTP_404_NOT_FOUND)

        try:
            quote = QuoteEngine(branch).issue(quote, actor=request.user)
        except PermissionError as e:
            return Response({'detail': str(e)}, status=status.HTTP_403_FORBIDDEN)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(QuoteDetailSerializer(quote).data)


class QuoteReviseView(APIView):
    """
    POST /api/v1/jobs/quotes/<pk>/revise/

    Returns the new version. The old one is kept and marked superseded —
    a customer may be holding it.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        branch, err = _branch_or_400(request)
        if err:
            return err

        quote = _get_quote(pk, branch)
        if not quote:
            return Response({'detail': 'Quote not found.'},
                            status=status.HTTP_404_NOT_FOUND)

        serializer = QuoteReviseSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            revision = QuoteEngine(branch).revise(
                quote     = quote,
                raw_lines = serializer.validated_data['line_items'],
                actor     = request.user,
                notes     = serializer.validated_data['notes'],
            )
        except PermissionError as e:
            return Response({'detail': str(e)}, status=status.HTTP_403_FORBIDDEN)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            QuoteDetailSerializer(revision).data,
            status=status.HTTP_201_CREATED,
        )


class QuoteConvertView(APIView):
    """
    POST /api/v1/jobs/quotes/<pk>/convert/

    The customer accepted. Creates the job on today's sheet and puts it in
    the cashier queue.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        from apps.jobs.api.serializers import JobListSerializer

        branch, err = _branch_or_400(request)
        if err:
            return err

        quote = _get_quote(pk, branch)
        if not quote:
            return Response({'detail': 'Quote not found.'},
                            status=status.HTTP_404_NOT_FOUND)

        serializer = QuoteConvertSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            job = QuoteEngine(branch).convert(
                quote        = quote,
                actor        = request.user,
                agreed_terms = serializer.validated_data['agreed_terms'],
            )
        except PermissionError as e:
            return Response({'detail': str(e)}, status=status.HTTP_403_FORBIDDEN)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                'detail' : f'{quote.proforma_number} accepted. '
                           f'{job.job_number} is now with the cashier.',
                'job'    : JobListSerializer(job, context={'request': request}).data,
                'quote'  : QuoteDetailSerializer(quote).data,
            },
            status=status.HTTP_201_CREATED,
        )