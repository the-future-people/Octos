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


def _promise_fields(job, predicted):
    """
    The promise Octos made, and whether it is in danger.

    Late: the promised time has passed and the work is not done. At risk:
    not late yet, but the floor's own prediction lands after the promise.
    A job with no promise is neither; nothing was promised to break.
    """
    from datetime import datetime
    from django.utils import timezone
    from apps.jobs.services.inspection import current_promise

    promise = current_promise(job)
    if promise is None:
        return {'promise': None, 'late': False, 'at_risk': False}

    late = timezone.now() > promise
    at_risk = False
    if not late and predicted and predicted.get('ready_at'):
        at_risk = datetime.fromisoformat(predicted['ready_at']) > promise

    return {'promise': promise.isoformat(), 'late': late, 'at_risk': at_risk}


class VerificationQueueView(APIView):
    """
    GET /api/v1/jobs/coordinator/verification-queue/

    Remote orders nobody at the branch has looked at yet, in the order
    they must be taken: soonest promise first. One is marked is_next for
    the coordinator asking; the rest wait. See services/inspection.py.

    Previously: Oldest first — a
    customer who ordered this morning has been waiting longer than one who
    ordered ten minutes ago.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.jobs.api.serializers import JobListSerializer

        branch, err = _branch_or_400(request)
        if err:
            return err

        from apps.jobs.services.inspection import (
            arrival_queue, claim_is_live, next_up,
        )

        # Which jobs wait and in what order lives in the service, so this
        # list and the claim that opens a job can never disagree about
        # what "next" means.
        queue = arrival_queue(branch)
        mine  = next_up(queue, request.user)

        data = JobListSerializer(
            queue, many=True, context={'request': request}
        ).data
        for row, job in zip(data, queue):
            predicted = _predicted_ready(job)
            row['predicted'] = predicted
            row.update(_promise_fields(job, predicted))

            held = claim_is_live(job)
            holder = job.inspecting_by if held else None
            row['is_next'] = mine is not None and job.pk == mine.pk
            row['inspecting_by_name'] = (
                (holder.full_name or holder.email) if holder else None
            )
            row['inspecting_is_me'] = bool(
                holder and holder.pk == request.user.pk
            )

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

        from django.db.models import Q

        jobs = (
            Job.objects
            .filter(branch=branch)
            .filter(
                Q(work_state__in=[
                    'RECEIVED', 'IN_PRODUCTION', 'FINISHING', 'QUALITY_CHECK',
                ])
                # Done and on the shelf. Leaves the board once handed over.
                | Q(work_state='DONE', handover_state='AWAITING_COLLECTION')
            )
            .exclude(status__in=['CANCELLED', 'DRAFT'])
            .exclude(job_type='INSTANT')
            # The coordinator has no business with work that has not been
            # paid for. The engine already refuses to start an unpaid job,
            # but refusing at the Start button means he has already opened
            # it and decided to work on it. Every job he sees is paid.
            .exclude(payment_state='UNPAID')
            .select_related('customer', 'intake_by')
            .prefetch_related('line_items__service', 'halts', 'verifications')
            .order_by('created_at')
        )

        columns = {
            'RECEIVED': [], 'IN_PRODUCTION': [],
            'FINISHING': [], 'QUALITY_CHECK': [],
            'READY': [],
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
            if job.work_state == 'DONE':
                # On the shelf. The promise was kept or it was not, and the
                # floor has nothing left to predict.
                columns['READY'].append(data)
                continue
            data['predicted'] = _predicted_ready(job)
            data.update(_promise_fields(job, data['predicted']))
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


class IntakeCheckView(APIView):
    """
    GET /api/v1/jobs/<pk>/intake-check/
    Can this be printed as ordered? Every piece, ordered vs file, row by
    row, with the checks a person signs. What the inspection modal shows.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        from apps.jobs.api.file_views import sign_file_id
        from apps.jobs.services.intake_check import compare

        branch, err = _branch_or_400(request)
        if err:
            return err
        if not _is_coordinator(request, branch):
            return Response({'detail': 'Only a coordinator can inspect.'},
                            status=status.HTTP_403_FORBIDDEN)
        job = _get_job(pk, branch)
        if not job:
            return Response({'detail': 'Job not found.'}, status=status.HTTP_404_NOT_FOUND)

        data = compare(job)
        for piece in data['pieces']:
            if piece['file']:
                fid = piece['file']['id']
                piece['file']['url'] = f'/api/v1/jobs/files/{fid}/?t={sign_file_id(fid)}'

        data['job'] = {
            'id':           job.pk,
            'job_number':   job.job_number,
            'customer':     job.customer.full_name if job.customer_id else 'Walk-in',
            'channel':      job.intake_channel,
            'arrived_at':   job.created_at.isoformat(),
            'ready_by':     job.estimated_ready_at.isoformat() if job.estimated_ready_at else None,
            'customer_note': '',
        }
        return Response(data)


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

        from django.db import transaction
        from apps.jobs.services.intake_check import gate, operator_notes

        # Nothing clears until every amber row is settled and both checks
        # only a person can make are signed. The server decides, not the
        # screen: an old tab or a direct call gets the same answer.
        signed = [s for s in (request.data.get('signed_checks') or []) if isinstance(s, str)]
        settled = request.data.get('settlements') or {}
        if not isinstance(settled, dict):
            settled = {}
        missing = gate(job, signed, settled)
        if missing:
            return Response(
                {'detail': 'First ' + ', '.join(missing) + '.', 'missing': missing},
                status=status.HTTP_400_BAD_REQUEST,
            )
        for_the_floor = operator_notes(job, settled)

        try:
            with transaction.atomic():
                verification = JobStatusEngine(job).verify(
                    actor              = request.user,
                    note               = request.data.get('note', ''),
                    customer_contacted = bool(request.data.get('customer_contacted')),
                    customer_response  = request.data.get('customer_response', ''),
                )
                if verification is not None and hasattr(verification, 'signed_checks'):
                    verification.signed_checks = signed
                    verification.settlements = settled
                    verification.save(update_fields=['signed_checks', 'settlements'])
                # "Print at 6 × 6 in": what intake agreed reaches the operator's card.
                if for_the_floor:
                    job.refresh_from_db(fields=['notes'])
                    job.notes = '\n'.join(p for p in [job.notes or '', *for_the_floor] if p)
                    job.save(update_fields=['notes', 'updated_at'])
        except PermissionError as e:
            return Response({'detail': str(e)}, status=status.HTTP_403_FORBIDDEN)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        from apps.jobs.services.inspection import release
        release(job, request.user)

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

class SuspendJobView(APIView):
    """
    POST /api/v1/jobs/<pk>/verify/suspend/
    Body: { outcome, note?, customer_contacted?, customer_response? }

    A job that has been inspected, is not cleared, and cannot proceed until
    someone answers a question. It is two facts, not one: what the
    coordinator found, and that the job is held while it stands.

    Recording only the halt would lose the finding — the job comes back to
    the workspace with a reason code and no account of what was wrong with
    it. Recording only the rejection would leave it sitting in the arrivals
    rail with a known problem and nothing showing it is held.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        from django.db import transaction
        from apps.core.broadcast import broadcast_invalidation

        branch, err = _branch_or_400(request)
        if err:
            return err

        job = _get_job(pk, branch)
        if not job:
            return Response({'detail': 'Job not found.'},
                            status=status.HTTP_404_NOT_FOUND)

        outcome = request.data.get('outcome')
        # PASSED is a clearance, not a suspension. Accepting it here would
        # record a job as both cleared and held.
        valid = [
            c[0] for c in JobVerification.Outcome.choices
            if c[0] != JobVerification.Outcome.PASSED
        ]
        if outcome not in valid:
            return Response(
                {'detail': f'Outcome must be one of: {", ".join(valid)}.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        note = request.data.get('note', '')

        try:
            # Both writes or neither. A rejection recorded without its halt
            # is the worse half-state: a known problem the board does not
            # show as stopped.
            with transaction.atomic():
                engine = JobStatusEngine(job)
                engine.reject_verification(
                    outcome            = outcome,
                    actor              = request.user,
                    note               = note,
                    customer_contacted = bool(request.data.get('customer_contacted')),
                    customer_response  = request.data.get('customer_response', ''),
                )
                engine.halt(
                    reason = 'AWAITING_CUSTOMER',
                    actor  = request.user,
                    note   = note,
                )
        except PermissionError as e:
            return Response({'detail': str(e)}, status=status.HTTP_403_FORBIDDEN)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        from apps.jobs.services.inspection import release
        release(job, request.user)

        broadcast_invalidation(branch.id, [
            'verificationQueue', 'suspendedJobs', 'productionBoard',
            'jobs', 'job-detail',
        ])
        return Response({
            'success':    True,
            'job_number': job.job_number,
            'detail':     f'{job.job_number} suspended— {outcome.replace("_", " ").lower()}.',
        })


class ClaimInspectionView(APIView):
    """
    POST /api/v1/jobs/<pk>/inspect/

    Take a job into the inspection workspace, or keep the claim alive
    while the workspace is open. Refused unless it is the coordinator's
    next job, so the strict queue holds even against a hand-made request.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        from apps.core.broadcast import broadcast_invalidation
        from apps.jobs.services.inspection import ClaimRefused, claim

        branch, err = _branch_or_400(request)
        if err:
            return err

        job = _get_job(pk, branch)
        if not job:
            return Response({'detail': 'Job not found.'},
                            status=status.HTTP_404_NOT_FOUND)

        if not JobStatusEngine(job)._may_move_axis('WORK', request.user):
            return Response(
                {'detail': 'Only a coordinator can inspect jobs.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            job = claim(pk, branch, request.user)
        except ClaimRefused as e:
            return Response({'detail': str(e)}, status=status.HTTP_409_CONFLICT)

        broadcast_invalidation(branch.id, ['verificationQueue'])
        return Response({
            'success':          True,
            'job_number':       job.job_number,
            'inspecting_since': job.inspecting_since.isoformat(),
        })


class ReleaseInspectionView(APIView):
    """
    POST /api/v1/jobs/<pk>/inspect/release/

    Close the workspace without clearing or suspending. Frees only the
    caller's own claim.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        from apps.core.broadcast import broadcast_invalidation
        from apps.jobs.services.inspection import release

        branch, err = _branch_or_400(request)
        if err:
            return err

        job = _get_job(pk, branch)
        if not job:
            return Response({'detail': 'Job not found.'},
                            status=status.HTTP_404_NOT_FOUND)

        release(job, request.user)
        broadcast_invalidation(branch.id, ['verificationQueue'])
        return Response({'success': True, 'job_number': job.job_number})


class ChangeSpecsView(APIView):
    """
    POST /api/v1/jobs/<pk>/lines/<line_id>/specs/
    Body: { changes: { field: new_value, ... }, customer_response }

    Correct a line's specification during inspection, after the
    customer agreed to it on the recorded company line. The rules live
    in services/spec_changes.py; this only checks who is asking.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk, line_id):
        from apps.core.broadcast import broadcast_invalidation
        from apps.jobs.services.spec_changes import (
            SpecChangeRefused, change_specs,
        )

        branch, err = _branch_or_400(request)
        if err:
            return err

        job = _get_job(pk, branch)
        if not job:
            return Response({'detail': 'Job not found.'},
                            status=status.HTTP_404_NOT_FOUND)

        if not JobStatusEngine(job)._may_move_axis('WORK', request.user):
            return Response(
                {'detail': 'Only a coordinator can change an order.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            recorded = change_specs(
                job_id            = pk,
                line_id           = line_id,
                changes           = request.data.get('changes'),
                customer_response = request.data.get('customer_response', ''),
                actor             = request.user,
            )
        except SpecChangeRefused as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        broadcast_invalidation(branch.id, ['job-detail', 'verificationQueue'])
        return Response({
            'success': True,
            'changes': [
                {
                    'field':      c.field,
                    'old_value':  c.old_value,
                    'new_value':  c.new_value,
                    'changed_at': c.changed_at.isoformat() if c.changed_at else None,
                }
                for c in recorded
            ],
        })


class SuspendedJobsView(APIView):
    """
    GET /api/v1/jobs/coordinator/suspended/

    Jobs inspected, held, and waiting on an answer. A separate list rather
    than part of the board: they are not on the floor, and a suspended job
    left in the arrivals rail would invite a coordinator to open a job
    somebody is already chasing.

    Oldest first, because a job held for three days is the one at risk.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.jobs.api.serializers import JobListSerializer

        branch, err = _branch_or_400(request)
        if err:
            return err

        candidates = (
            Job.objects
            .filter(branch=branch, work_state='RECEIVED')
            .exclude(status__in=['CANCELLED', 'DRAFT'])
            .select_related('customer', 'intake_by')
            .prefetch_related('line_items__service', 'verifications', 'halts')
            .order_by('created_at')
        )

        rows = []
        for job in candidates:
            active = next(
                (h for h in job.halts.all() if h.resumed_at is None), None
            )
            if not active or job.is_verified:
                continue
            data = JobListSerializer(job, context={'request': request}).data
            # What was found and when it stopped — the coordinator picking
            # this up later did not necessarily suspend it.
            data['halt'] = {
                'reason':    active.reason,
                'note':      active.note,
                'halted_at': active.halted_at.isoformat() if active.halted_at else None,
            }
            latest = job.verifications.order_by('-checked_at').first()
            data['finding'] = latest.outcome if latest else None
            rows.append(data)

        return Response(rows)

# ── The floor: machines, their line-ups, and moving work on ──────

def _is_coordinator(request, branch):
    """Only floor roles move work on."""
    from apps.core.finance_scope import get_role_name
    return get_role_name(request.user) in {
        'FLOW_COORDINATOR', 'BRANCH_MANAGER', 'REGIONAL_MANAGER',
        'BELT_MANAGER', 'SUPER_ADMIN',
    }


class FloorView(APIView):
    """
    GET /api/v1/jobs/coordinator/floor/

    Every machine with its line-up, the bench, and anything unassigned.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.jobs.services.floor import floor

        branch, err = _branch_or_400(request)
        if err:
            return err
        return Response(floor(branch))


class StepDoneView(APIView):
    """POST /api/v1/jobs/steps/<step_id>/done/   Body: { override } (a reason; needed on a staffed machine)"""
    permission_classes = [IsAuthenticated]

    def post(self, request, step_id):
        from apps.core.broadcast import broadcast_invalidation
        from apps.jobs.services.steps import StepRefused, mark_done

        branch, err = _branch_or_400(request)
        if err:
            return err
        if not _is_coordinator(request, branch):
            return Response({'detail': 'Only a coordinator can move work on.'},
                            status=status.HTTP_403_FORBIDDEN)
        try:
            # On a staffed machine the service refuses without a reason:
            # Done is the operator's, and an override is signed and kept.
            step = mark_done(step_id, branch, request.user,
                             override=request.data.get('override') or '')
        except StepRefused as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        broadcast_invalidation(branch.id, ['floor', 'productionBoard', 'job-detail'])
        return Response({'success': True, 'job_number': step.job.job_number})


class StepMoveView(APIView):
    """POST /api/v1/jobs/steps/<step_id>/move/   Body: { machine }"""
    permission_classes = [IsAuthenticated]

    def post(self, request, step_id):
        from apps.core.broadcast import broadcast_invalidation
        from apps.jobs.services.steps import StepRefused, move_step

        branch, err = _branch_or_400(request)
        if err:
            return err
        if not _is_coordinator(request, branch):
            return Response({'detail': 'Only a coordinator can move work.'},
                            status=status.HTTP_403_FORBIDDEN)
        try:
            step = move_step(step_id, branch, request.data.get('machine'), request.user)
        except StepRefused as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        broadcast_invalidation(branch.id, ['floor', 'productionBoard'])
        return Response({'success': True, 'machine': step.machine.name})

class StepCheckView(APIView):
    """
    GET  /api/v1/jobs/steps/<step_id>/check/   what was ordered, row by row
    POST /api/v1/jobs/steps/<step_id>/check/   Body: { made: {field: value}, note? }

    The final check at a piece's last step. Matches: ready, and the
    customer is told once every piece is. Differs: back to be made again.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, step_id):
        from django.utils import timezone
        from apps.jobs.models import JobStep
        from apps.jobs.services.final_check import ordered_rows

        branch, err = _branch_or_400(request)
        if err:
            return err
        step = (
            JobStep.objects
            .select_related('job__customer', 'line_item__service')
            .filter(pk=step_id, job__branch=branch)
            .first()
        )
        if step is None:
            return Response({'detail': 'Step not found.'}, status=status.HTTP_404_NOT_FOUND)

        job = step.job
        return Response({
            'step':          step.pk,
            'job_number':    job.job_number,
            'line':          step.line_item.label or step.line_item.service.name,
            'customer_name': job.customer.full_name if job.customer_id else 'Walk-in',
            'intake_channel': job.intake_channel,
            'rows':          ordered_rows(step.line_item),
            'promise':       job.estimated_ready_at.isoformat() if job.estimated_ready_at else None,
            'now':           timezone.now().isoformat(),
        })

    def post(self, request, step_id):
        from apps.core.broadcast import broadcast_invalidation
        from apps.jobs.services.final_check import check
        from apps.jobs.services.steps import StepRefused

        branch, err = _branch_or_400(request)
        if err:
            return err
        if not _is_coordinator(request, branch):
            return Response({'detail': 'Only a coordinator can check work.'},
                            status=status.HTTP_403_FORBIDDEN)
        made = request.data.get('made') or {}
        if not isinstance(made, dict):
            return Response({'detail': 'made must be an object.'},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            record = check(step_id, branch, request.user, made=made,
                           note=request.data.get('note', ''))
        except StepRefused as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        broadcast_invalidation(branch.id, ['floor', 'productionBoard', 'job-detail'])
        return Response({'outcome': record.outcome, 'rows': record.rows})