"""
Proforma API.

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
from apps.jobs.services.proforma_engine import ProformaEngine

from .proforma_serializers import (
    ProformaCreateSerializer, ProformaReviseSerializer, ProformaConvertSerializer,
    ProformaListSerializer, ProformaDetailSerializer,
)


def _branch_or_400(request):
    branch = getattr(request.user, 'branch', None)
    if not branch:
        return None, Response(
            {'detail': 'No branch assigned.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return branch, None


def _get_proforma(pk, branch):
    return ProformaInvoice.objects.select_related(
        'customer', 'issued_by', 'converted_by', 'supersedes', 'job',
    ).filter(pk=pk, branch=branch).first()


class ProformaListView(generics.ListAPIView):
    """
    GET /api/v1/jobs/proformas/?status=ISSUED

    Superseded versions are hidden by default. They are kept as documents
    and reachable through a proforma's revision chain, but a list of every
    draft price a customer was ever shown is noise.
    """
    serializer_class   = ProformaListSerializer
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


class ProformaDetailView(generics.RetrieveAPIView):
    serializer_class   = ProformaDetailSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        branch = getattr(self.request.user, 'branch', None)
        if not branch:
            return ProformaInvoice.objects.none()
        return ProformaInvoice.objects.select_related(
            'customer', 'issued_by', 'converted_by', 'supersedes', 'job',
        ).filter(branch=branch)


class ProformaCreateView(APIView):
    """POST /api/v1/jobs/proformas/create/ — creates a DRAFT."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from apps.customers.models import CustomerProfile

        branch, err = _branch_or_400(request)
        if err:
            return err

        serializer = ProformaCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        try:
            customer = CustomerProfile.objects.get(pk=data['customer'])
        except CustomerProfile.DoesNotExist:
            return Response(
                {'detail': 'Customer not found. Proformas go to registered customers only.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            proforma = ProformaEngine(branch).create(
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
            ProformaDetailSerializer(proforma).data,
            status=status.HTTP_201_CREATED,
        )


class ProformaIssueView(APIView):
    """POST /api/v1/jobs/proformas/<pk>/issue/ — sends it; the clock starts."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        branch, err = _branch_or_400(request)
        if err:
            return err

        proforma = _get_proforma(pk, branch)
        if not proforma:
            return Response({'detail': 'Proforma not found.'},
                            status=status.HTTP_404_NOT_FOUND)

        try:
            proforma = ProformaEngine(branch).issue(proforma, actor=request.user)
        except PermissionError as e:
            return Response({'detail': str(e)}, status=status.HTTP_403_FORBIDDEN)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(ProformaDetailSerializer(proforma).data)


class ProformaReviseView(APIView):
    """
    POST /api/v1/jobs/proformas/<pk>/revise/

    Returns the new version. The old one is kept and marked superseded —
    a customer may be holding it.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        branch, err = _branch_or_400(request)
        if err:
            return err

        proforma = _get_proforma(pk, branch)
        if not proforma:
            return Response({'detail': 'Proforma not found.'},
                            status=status.HTTP_404_NOT_FOUND)

        serializer = ProformaReviseSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            revision = ProformaEngine(branch).revise(
                proforma     = proforma,
                raw_lines = serializer.validated_data['line_items'],
                actor     = request.user,
                notes     = serializer.validated_data['notes'],
            )
        except PermissionError as e:
            return Response({'detail': str(e)}, status=status.HTTP_403_FORBIDDEN)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            ProformaDetailSerializer(revision).data,
            status=status.HTTP_201_CREATED,
        )


class ProformaConvertView(APIView):
    """
    POST /api/v1/jobs/proformas/<pk>/convert/

    The customer accepted. Creates the job on today's sheet and puts it in
    the cashier queue.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        from apps.jobs.api.serializers import JobListSerializer

        branch, err = _branch_or_400(request)
        if err:
            return err

        proforma = _get_proforma(pk, branch)
        if not proforma:
            return Response({'detail': 'Proforma not found.'},
                            status=status.HTTP_404_NOT_FOUND)

        serializer = ProformaConvertSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            job = ProformaEngine(branch).convert(
                proforma        = proforma,
                actor        = request.user,
                agreed_terms = serializer.validated_data['agreed_terms'],
            )
        except PermissionError as e:
            return Response({'detail': str(e)}, status=status.HTTP_403_FORBIDDEN)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                'detail' : f'{proforma.proforma_number} accepted. '
                           f'{job.job_number} is now with the cashier.',
                'job'    : JobListSerializer(job, context={'request': request}).data,
                'proforma'  : ProformaDetailSerializer(proforma).data,
            },
            status=status.HTTP_201_CREATED,
        )

class ProformaPDFView(APIView):
    """
    GET /api/v1/jobs/proformas/<pk>/pdf/

    Streams the document. Nothing is written to disk: MEDIA_ROOT is an
    ephemeral container filesystem, and a proforma is fully derivable from
    its stored lines, so a saved file would be a stale copy waiting to be
    destroyed on the next deploy.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        from django.http import HttpResponse
        from apps.jobs.pdf.proforma_pdf import build_proforma_pdf

        branch, err = _branch_or_400(request)
        if err:
            return err

        proforma = _get_proforma(pk, branch)
        if not proforma:
            return Response({'detail': 'Proforma not found.'},
                            status=status.HTTP_404_NOT_FOUND)

        try:
            pdf = build_proforma_pdf(proforma)
        except Exception as e:
            return Response({'detail': f'Could not build the document: {e}'},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        response = HttpResponse(pdf, content_type='application/pdf')
        response['Content-Disposition'] = (
            f'attachment; filename="{proforma.proforma_number}.pdf"'
        )
        return response