"""
The waiting-area board: what is being made, and what is ready.

GET board/<branch_code>/?key=…

For a TV in the shop, open to anyone with the key, so the screen needs
no staff login. It shows short numbers and nothing else: no names, no
phone numbers, no PINs. Online orders show the last three digits of
their order number (036); counter jobs show C- and the last three of
theirs (C-441), so the two never clash.

The key is BOARD_KEY in Railway's settings. Without it the board is
switched off.
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
    'PENDING': 'in the queue',
    'QUEUED': 'in the queue',
    'INSPECTING': 'being checked',
    'IN_PRODUCTION': 'printing',
    'PRINTING': 'printing',
    'FINISHING': 'finishing',
    'QUALITY_CHECK': 'final check',
}

# A job not collected within this long drops off the board: the shelf
# keeps it, the screen does not need to.
WINDOW = timedelta(days=3)


def _digits(text):
    return ''.join(ch for ch in str(text or '') if ch.isdigit())


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
        online = {
            o.job_id: o
            for o in OnlineOrder.objects.filter(job_id__in=[j.pk for j in jobs])
        }

        making, ready = [], []
        for job in jobs:
            order = online.get(job.pk)
            short = (_digits(order.order_number)[-3:] if order
                     else 'C-' + _digits(getattr(job, 'job_number', '') or job.pk)[-3:])
            if job.work_state == 'DONE':
                ready.append({'n': short, 'since': job.updated_at.isoformat()})
            else:
                making.append({
                    'n': short,
                    'stage': STAGE_WORDS.get(job.work_state, 'in the queue'),
                    'ready_about': order.promised_for.isoformat() if order and order.promised_for else None,
                })

        ready.sort(key=lambda r: r['since'], reverse=True)
        return Response({
            'branch': branch_code.upper(),
            'now': now.isoformat(),
            'making': making[:12],
            'ready': ready[:24],
        })