"""
Coordinator API.

The coordinator is the back room. They verify what arrives remotely, move
work through production, and halt when a machine goes down. They never meet
a customer at the counter, and they never touch money.
"""

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.jobs.models import Job, JobVerification
from apps.jobs.status_engine import JobStatusEngine


def _branch_or_400(request):
    branch = getattr(request.user, 'branch', None)
    if not branch:
        return None, Response(
            {'detail': 'No branch assigned.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return branch, None


def _get_job(pk, branch):
    return (
        Job.objects
        .select_related('branch', 'customer', 'intake_by')
        .prefetch_related('line_items__service', 'halts', 'verifications')
        .filter(pk=pk, branch=branch)
        .first()
    )


def _predicted_ready(job):
    """
    When the floor says this job will be done. Returns None where the job
    has no priceable route or the branch has no machines for it — better
    nothing than a number nobody can hit.
    """
    from apps.production.services.prediction_service import PredictionService

    try:
        lines = [
            (li.service, li.quantity or 1, li.pages or 1)
            for li in job.line_items.all()
        ]
        if not lines:
            return None
        p = PredictionService(job.branch).predict(lines)
        return {
            'ready_at':    p.ready_at.isoformat(),
            'minutes':     p.total_minutes,
            'is_next_day': p.is_next_day,
            'confidence':  p.confidence,
        }
    except Exception:
        # A prediction failing must never take the board down with it.
        return None


class VerificationQueueView(APIView):
    """
    GET /api/v1/jobs/coordinator/verification-queue/

    Remote orders nobody at the branch has looked at yet. Oldest first — a
    customer who ordered this morning has been waiting longer than one who
    ordered ten minutes ago.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.jobs.api.serializers import JobListSerializer

        branch, err = _branch_or_400(request)
        if err:
            return err

        candidates = (
            Job.objects
            .filter(
                branch=branch,
                intake_channel__in=Job.REMOTE_CHANNELS,
                work_state='RECEIVED',
            )
            .exclude(status__in=['CANCELLED', 'DRAFT'])
            .select_related('customer', 'intake_by')
            .prefetch_related('line_items__service', 'verifications', 'halts')
            .order_by('created_at')
        )

        # is_verified reads the latest verification, which is a property
        # rather than a column, so the filter happens here.
        pending = [j for j in candidates if not j.is_verified]

        data = JobListSerializer(
            pending, many=True, context={'request': request}
        ).data
        for row, job in zip(data, pending):
            row['predicted'] = _predicted_ready(job)

        return Response(data)


class ProductionBoardView(APIView):
    """
    GET /api/v1/jobs/coordinator/board/

    Everything on the floor, grouped by work state. This is the
    coordinator's whole screen: what is waiting, what is running, what is
    finishing, and what has stopped.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.jobs.api.serializers import JobListSerializer

        branch, err = _branch_or_400(request)
        if err:
            return err

        jobs = (
            Job.objects
            .filter(
                branch=branch,
                work_state__in=[
                    'RECEIVED', 'IN_PRODUCTION', 'FINISHING', 'QUALITY_CHECK',
                ],
            )
            .exclude(status__in=['CANCELLED', 'DRAFT'])
            .exclude(job_type='INSTANT')
            .select_related('customer', 'intake_by')
            .prefetch_related('line_items__service', 'halts', 'verifications')
            .order_by('created_at')
        )

        columns = {
            'RECEIVED': [], 'IN_PRODUCTION': [],
            'FINISHING': [], 'QUALITY_CHECK': [],
        }
        halted = []

        for job in jobs:
            # A job still waiting to be checked is not on the floor. It
            # belongs in the arrivals rail alone, or a coordinator sees the
            # same job twice and can press Start on something nobody has
            # opened the file for.
            if job.needs_verification and not job.is_verified:
                continue
            data = JobListSerializer(job, context={'request': request}).data
            data['predicted'] = _predicted_ready(job)
            # A halted job is shown apart rather than in its column. It is
            # not being worked on, and leaving it in place makes a column
            # look busier than the floor actually is.
            if any(h.resumed_at is None for h in job.halts.all()):
                halted.append(data)
            else:
                columns[job.work_state].append(data)

        return Response({
            'columns': columns,
            'halted':  halted,
            'counts': {
                **{k: len(v) for k, v in columns.items()},
                'HALTED': len(halted),
            },
        })


class VerifyJobView(APIView):
    """
    POST /api/v1/jobs/<pk>/verify/
    Body: { note?, customer_contacted?, customer_response? }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        from apps.core.broadcast import broadcast_invalidation

        branch, err = _branch_or_400(request)
        if err:
            return err

        job = _get_job(pk, branch)
        if not job:
            return Response({'detail': 'Job not found.'},
                            status=status.HTTP_404_NOT_FOUND)

        try:
            verification = JobStatusEngine(job).verify(
                actor              = request.user,
                note               = request.data.get('note', ''),
                customer_contacted = bool(request.data.get('customer_contacted')),
                customer_response  = request.data.get('customer_response', ''),
            )
        except PermissionError as e:
            return Response({'detail': str(e)}, status=status.HTTP_403_FORBIDDEN)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        broadcast_invalidation(branch.id, [
            'verificationQueue', 'productionBoard', 'jobs', 'job-detail',
        ])
        return Response({
            'success':    True,
            'job_number': job.job_number,
            'detail':     f'{job.job_number} cleared for production.',
            'checked_at': verification.checked_at.isoformat(),
        })


class RejectVerificationView(APIView):
    """
    POST /api/v1/jobs/<pk>/verify/reject/
    Body: { outcome, note?, customer_contacted?, customer_response? }

    Records why a job cannot proceed as sent. Does not halt it — halting is
    a separate, deliberate act.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        from apps.core.broadcast import broadcast_invalidation

        branch, err = _branch_or_400(request)
        if err:
            return err

        job = _get_job(pk, branch)
        if not job:
            return Response({'detail': 'Job not found.'},
                            status=status.HTTP_404_NOT_FOUND)

        outcome = request.data.get('outcome')
        valid   = [c[0] for c in JobVerification.Outcome.choices]
        if outcome not in valid:
            return Response(
                {'detail': f'Outcome must be one of: {", ".join(valid)}.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            JobStatusEngine(job).reject_verification(
                outcome            = outcome,
                actor              = request.user,
                note               = request.data.get('note', ''),
                customer_contacted = bool(request.data.get('customer_contacted')),
                customer_response  = request.data.get('customer_response', ''),
            )
        except PermissionError as e:
            return Response({'detail': str(e)}, status=status.HTTP_403_FORBIDDEN)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        broadcast_invalidation(branch.id, [
            'verificationQueue', 'productionBoard', 'jobs', 'job-detail',
        ])
        return Response({
            'success':    True,
            'job_number': job.job_number,
            'detail':     f'{job.job_number} sent back — {outcome.replace("_", " ").lower()}.',
        })