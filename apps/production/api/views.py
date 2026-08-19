"""
Machine API.

Marking a machine down is the coordinator's — they live with the machines
and are the ones affected. The asset register, adding and removing devices,
belongs to the branch manager, and will move to HQ once there are several
branches.
"""

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.production.models import Machine
from apps.production.services.machine_service import MachineService


def _branch_or_400(request):
    branch = getattr(request.user, 'branch', None)
    if not branch:
        return None, Response(
            {'detail': 'No branch assigned.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return branch, None


def _serialise(machine, open_halts=0):
    return {
        'id':                 machine.id,
        'name':               machine.name,
        'model_number':       machine.model_number,
        'machine_type':       machine.machine_type.code,
        'machine_type_name':  machine.machine_type.name,
        'station':            machine.machine_type.station.code,
        'station_name':       machine.machine_type.station.name,
        'is_active':          machine.is_active,
        'is_available':       machine.is_available,
        'is_usable':          machine.is_usable,
        'unavailable_reason': machine.unavailable_reason,
        'unavailable_since':  machine.unavailable_since.isoformat()
                              if machine.unavailable_since else None,
        'halted_jobs':        open_halts,
    }


class MachineListView(APIView):
    """
    GET /api/v1/production/machines/

    Every machine at this branch, in station order — printing before
    laminating before binding, which is the order work travels.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.jobs.models import JobHalt

        branch, err = _branch_or_400(request)
        if err:
            return err

        machines = (
            Machine.objects
            .filter(branch=branch, is_active=True)
            .select_related('machine_type__station')
            .order_by('machine_type__station__sequence', 'name')
        )

        # How many jobs each machine is currently holding up. The number a
        # coordinator wants before deciding whether a repair can wait.
        halt_counts = {}
        for halt in JobHalt.objects.filter(
            machine__branch=branch, resumed_at__isnull=True,
        ).values_list('machine_id', flat=True):
            halt_counts[halt] = halt_counts.get(halt, 0) + 1

        return Response([
            _serialise(m, halt_counts.get(m.id, 0)) for m in machines
        ])


class MachineDownView(APIView):
    """
    POST /api/v1/production/machines/<pk>/down/
    Body: { reason, note? }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        from apps.core.broadcast import broadcast_invalidation

        branch, err = _branch_or_400(request)
        if err:
            return err

        machine = Machine.objects.filter(
            pk=pk, branch=branch, is_active=True,
        ).select_related('machine_type__station').first()
        if not machine:
            return Response({'detail': 'Machine not found.'},
                            status=status.HTTP_404_NOT_FOUND)

        reason = (request.data.get('reason') or '').strip()
        if not reason:
            return Response({'detail': 'A reason is required.'},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            result = MachineService.mark_down(
                machine=machine,
                reason=reason,
                actor=request.user,
                note=request.data.get('note', ''),
            )
        except PermissionError as e:
            return Response({'detail': str(e)}, status=status.HTTP_403_FORBIDDEN)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        broadcast_invalidation(branch.id, [
            'machines', 'productionBoard', 'jobs', 'jobStats',
        ])
        return Response(result)


class MachineUpView(APIView):
    """
    POST /api/v1/production/machines/<pk>/up/
    Body: { resume_jobs? }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        from apps.core.broadcast import broadcast_invalidation

        branch, err = _branch_or_400(request)
        if err:
            return err

        machine = Machine.objects.filter(
            pk=pk, branch=branch, is_active=True,
        ).select_related('machine_type__station').first()
        if not machine:
            return Response({'detail': 'Machine not found.'},
                            status=status.HTTP_404_NOT_FOUND)

        resume = request.data.get('resume_jobs')
        resume = True if resume is None else bool(resume)

        try:
            result = MachineService.mark_up(
                machine=machine,
                actor=request.user,
                resume_jobs=resume,
            )
        except PermissionError as e:
            return Response({'detail': str(e)}, status=status.HTTP_403_FORBIDDEN)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        broadcast_invalidation(branch.id, [
            'machines', 'productionBoard', 'jobs', 'jobStats',
        ])
        return Response(result)