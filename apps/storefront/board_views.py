"""
The waiting-area board: what is being made, and what is ready.

GET board/<branch_code>/?key=…

For a TV in the shop, open to anyone with the key, so the screen needs
no staff login. Each job shows its full number (as on the customer's
receipt or SMS), the service, and when it will be or has been ready.
Never a name, a phone number, a PIN or anything from the job's own
contents: what someone ordered is shown at the level of the service only.

The key is BOARD_KEY in Railway's settings. Without it the board is off.
"""

import secrets
from datetime import timedelta

from decouple import config
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

# The customer's words for where a job is on the floor.
STAGE_WORDS = {
    'PENDING': 'In queue',
    'QUEUED': 'In queue',
    'INSPECTING': 'Checking',
    'IN_PRODUCTION': 'Printing',
    'PRINTING': 'Printing',
    'FINISHING': 'Finishing',
    'QUALITY_CHECK': 'Final check',
}

# Not collected within this long, and it leaves the board: the shelf
# keeps it, the screen does not need to.
WINDOW = timedelta(days=3)


def _first_services(job_ids):
    """The first item's service on each job: what the board calls it."""
    from apps.jobs.models import JobLineItem
    names = {}
    for line in (JobLineItem.objects.filter(job_id__in=job_ids, parent__isnull=True)
                 .select_related('service').order_by('id')):
        if line.job_id not in names and line.service_id:
            names[line.job_id] = getattr(line.service, 'display_name', '') or line.service.name
    return names


class BoardView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, branch_code):
        from apps.jobs.models import Job
        from apps.storefront.models import OnlineOrder

        key = config('BOARD_KEY', default='')
        if not key:
            return Response({'detail': 'The board is not switched on.'},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        if not secrets.compare_digest(str(request.query_params.get('key', '')), key):
            return Response({'detail': 'Wrong key.'}, status=status.HTTP_403_FORBIDDEN)

        now = timezone.now()
        jobs = list(
            Job.objects.filter(branch__code__iexact=branch_code, created_at__gte=now - WINDOW)
            .exclude(handover_state='HANDED_OVER')
            .exclude(status__in=['CANCELLED', 'VOIDED', 'VOID'])
            .order_by('created_at')
        )
        ids = [j.pk for j in jobs]
        online = {o.job_id: o for o in OnlineOrder.objects.filter(job_id__in=ids)}
        services = _first_services(ids)

        making, ready = [], []
        for job in jobs:
            order = online.get(job.pk)
            number = order.order_number if order else (getattr(job, 'job_number', '') or str(job.pk))
            if order and not services.get(job.pk):
                first = (order.line_items or [{}])[0]
                services[job.pk] = first.get('service_name', '')
            item = {'number': number, 'service': services.get(job.pk, '')}
            if job.work_state == 'DONE':
                item['since'] = job.updated_at.isoformat()
                ready.append(item)
            else:
                item['stage'] = STAGE_WORDS.get(job.work_state, 'In queue')
                item['ready_about'] = order.promised_for.isoformat() if order and order.promised_for else None
                making.append(item)

        ready.sort(key=lambda r: r['since'], reverse=True)
        return Response({
            'branch': branch_code.upper(),
            'now': now.isoformat(),
            'making': making[:60],
            'ready': ready[:60],
        })