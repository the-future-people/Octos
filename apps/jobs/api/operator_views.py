"""
The operator's machine screen.

An operator is whoever is currently assigned to a machine (MachineOperator),
whatever their role. They see the work on their machines in Octos's
order, and nothing about money. Start and Done are theirs; the order is
not. Unlocking the screen checks their own account password.

    GET  /api/v1/jobs/operator/queue/
    POST /api/v1/jobs/operator/steps/<id>/start/
    POST /api/v1/jobs/operator/steps/<id>/done/     { made, spoilt }
    POST /api/v1/jobs/operator/steps/<id>/problem/  { kind, note }
    kind: MACHINE_DOWN | FILE_FAULT | MATERIAL_OUT
    POST /api/v1/jobs/operator/unlock/              { password }
"""

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .coordinator_views import _branch_or_400

INVALIDATE = ['floor', 'productionBoard', 'job-detail', 'operatorQueue']


def _my_machines(user, branch):
    from apps.production.models import Machine
    return (
        Machine.objects
        .filter(
            branch=branch, is_active=True,
            operator_assignments__operator=user,
            operator_assignments__active_until__isnull=True,
        )
        .select_related('machine_type')
        .distinct()
        .order_by('name')
    )


def _is_reprint(step):
    from apps.jobs.models import FinalCheck
    return FinalCheck.objects.filter(
        line_item_id=step.line_item_id, outcome=FinalCheck.Outcome.SENT_BACK,
    ).exists()


def _row(step, now):
    """One piece of work as the operator sees it. No prices, no customer contact."""
    job, line = step.job, step.line_item
    left = float(getattr(step, 'minutes_left', 0) or 0)
    slack = None
    if job.estimated_ready_at:
        slack = round((job.estimated_ready_at - now).total_seconds() / 60 - left)
    return {
        'step':           step.pk,
        'state':          step.state,
        'job_number':     job.job_number,
        'title':          line.service.name,
        'quantity':       line.quantity,
        'pages':          line.pages,
        'is_color':       getattr(line, 'is_color', None),
        'paper_size':     getattr(line, 'paper_size', None),
        'specifications': line.specifications or {},
        'instructions':   job.notes or '',
        'ready_at':       job.estimated_ready_at.isoformat() if job.estimated_ready_at else None,
        'slack_minutes':  slack,
        'minutes_left':   left,
        'machine':        {'id': step.machine_id, 'name': step.machine.name if step.machine_id else None},
        'started_at':     step.started_at.isoformat() if step.started_at else None,
        'is_reprint':     _is_reprint(step),
    }


class OperatorQueueView(APIView):
    """
    The operator's machines and their work: what is running on each, what
    comes next on each idle one, and everything behind, in slack order
    across all their machines.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.jobs.models import JobStep
        from apps.jobs.services.steps import queue

        branch, err = _branch_or_400(request)
        if err:
            return err
        machines = list(_my_machines(request.user, branch))
        if not machines:
            return Response({'detail': 'You are not assigned to a machine.'},
                            status=status.HTTP_403_FORBIDDEN)

        now = timezone.now()
        per_machine, behind = [], []
        for machine in machines:
            line_up = list(queue(branch, machine=machine).select_related('line_item__service'))
            running = line_up[0] if line_up and line_up[0].state == JobStep.State.ACTIVE else None
            rest = line_up[1:] if running else line_up
            nxt = rest[0] if (rest and running is None and machine.is_usable) else None
            per_machine.append({
                'id':           machine.pk,
                'name':         machine.name,
                'available':    machine.is_usable,
                'down_reason':  machine.unavailable_reason or '',
                'running':      _row(running, now) if running else None,
                'next':         _row(nxt, now) if nxt else None,
            })
            behind += [s for s in rest if s is not nxt]

        behind.sort(key=lambda s: (s.start_by is None, s.start_by or 0, s.job.created_at, s.pk))
        return Response({
            'operator': {
                'name':     request.user.full_name or request.user.email,
                'initials': ((request.user.first_name or ' ')[0] + (request.user.last_name or ' ')[0]).strip().upper(),
            },
            'branch':   branch.name,
            'machines': per_machine,
            'queue':    [_row(s, now) for s in behind],
        })


class OperatorStartView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, step_id):
        from apps.core.broadcast import broadcast_invalidation
        from apps.jobs.services.steps import StepRefused, start_step

        branch, err = _branch_or_400(request)
        if err:
            return err
        try:
            step = start_step(step_id, branch, request.user)
        except StepRefused as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        broadcast_invalidation(branch.id, INVALIDATE)
        return Response({'success': True, 'job_number': step.job.job_number})


class OperatorDoneView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, step_id):
        from apps.core.broadcast import broadcast_invalidation
        from apps.jobs.models import JobStep
        from apps.jobs.services.steps import StepRefused, mark_done

        branch, err = _branch_or_400(request)
        if err:
            return err

        counts = {}
        for field in ('made', 'spoilt'):
            try:
                counts[field] = int(request.data.get(field))
            except (TypeError, ValueError):
                counts[field] = -1
            if counts[field] < 0:
                return Response({'detail': 'Enter how many were made and spoilt.'},
                                status=status.HTTP_400_BAD_REQUEST)

        step = JobStep.objects.filter(pk=step_id, job__branch=branch).only('machine_id').first()
        mine = set(_my_machines(request.user, branch).values_list('pk', flat=True))
        if step is None or step.machine_id not in mine:
            return Response({'detail': 'That job is not on your machine.'},
                            status=status.HTTP_403_FORBIDDEN)
        try:
            step = mark_done(step_id, branch, request.user,
                             made=counts['made'], spoilt=counts['spoilt'])
        except StepRefused as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        broadcast_invalidation(branch.id, INVALIDATE)
        return Response({'success': True, 'job_number': step.job.job_number})


class OperatorProblemView(APIView):
    """Machine down, file fault or material out, on the job that is running."""
    permission_classes = [IsAuthenticated]

    def post(self, request, step_id):
        from apps.core.broadcast import broadcast_invalidation
        from apps.jobs.services.steps import StepRefused, report_problem

        branch, err = _branch_or_400(request)
        if err:
            return err
        kind = (request.data.get('kind') or '').strip().upper()
        note = (request.data.get('note') or '').strip()[:200]
        try:
            result = report_problem(step_id, branch, request.user, kind, note)
        except StepRefused as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        broadcast_invalidation(branch.id, INVALIDATE + ['machines'])
        return Response({'success': True, **result})


class OperatorUnlockView(APIView):
    """The screen locks on its own; unlocking checks the operator's own password."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        password = request.data.get('password') or ''
        if not password or not request.user.check_password(password):
            return Response({'detail': "That password isn't right."},
                            status=status.HTTP_403_FORBIDDEN)
        return Response({'success': True})