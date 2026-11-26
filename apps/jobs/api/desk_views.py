"""
The attendant's Work tab: front-desk jobs (14 Nov 2026).

Thin on purpose. Who may do what lives in the status engine
(_desk_may_move) and the rules in services/front_desk.py; these views
only find the job, ask, and say what happened.
"""
from datetime import timedelta

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.jobs.models import Job, JobVerification
from apps.jobs.services import counter_orders, front_desk
from apps.jobs.services.counter_orders import CounterRefused
from apps.jobs.services.front_desk import DeskRefused


def _branch_or_400(request):
    branch = getattr(request.user, 'branch', None)
    if not branch:
        return None, Response({'detail': 'No branch assigned.'}, status=status.HTTP_400_BAD_REQUEST)
    return branch, None


def _desk_job(pk, branch):
    return (
        Job.objects
        .select_related('branch', 'customer', 'desk_taken_by')
        .prefetch_related('line_items__service', 'halts', 'verifications')
        .filter(pk=pk, branch=branch, front_desk=True)
        .first()
    )


def _source(job):
    """Where it came from, as the attendant would say it."""
    try:
        order = job.online_order
    except Exception:
        order = None
    if job.counter_code:
        return 'WhatsApp order, pays at the counter'
    if order is not None:
        whatsapp = 'Taken by Octos on WhatsApp' in (order.notes or '')
        return f'{"WhatsApp" if whatsapp else "Print Octos"} order {order.order_number}'
    return job.get_intake_channel_display()


def _files(job):
    from apps.jobs.api.file_views import sign_file_id
    from apps.jobs.models import JobFile

    return [
        {
            'id':    f.pk,
            'name':  f.original_filename,
            'pages': f.page_count,
            'url':   f'/api/v1/jobs/files/{f.pk}/?t={sign_file_id(f.pk)}',
        }
        for f in JobFile.objects.filter(job=job).order_by('pk')
    ]


def _row(job, user, now):
    """Everything the Work tab and the arrival modal show for one job."""
    halt = next((h for h in job.halts.all() if h.resumed_at is None), None)
    finding = None
    if halt:
        latest = max(job.verifications.all(), key=lambda v: v.checked_at, default=None)
        finding = latest.outcome if latest else None
    taker = job.desk_taken_by
    return {
        'id':            job.pk,
        'job_number':    job.job_number,
        'title':         job.title,
        'customer':      job.customer.full_name if job.customer_id else 'Walk-in',
        'phone':         job.customer.phone if job.customer_id else '',
        'source':        _source(job),
        'paid':          str(job.amount_paid or 0),
        'payment_state': job.payment_state,
        'promise':       job.estimated_ready_at.isoformat() if job.estimated_ready_at else None,
        'landed_at':     front_desk.landed_at(job, now).isoformat(),
        'work_state':    job.work_state,
        'checked':       job.is_verified,
        'taken_by':      (taker.full_name or taker.email) if taker else None,
        'taken_is_me':   bool(taker and taker.pk == user.pk),
        'taken_at':      job.desk_taken_at.isoformat() if job.desk_taken_at else None,
        'held':          {'reason': halt.reason, 'note': halt.note, 'finding': finding} if halt else None,
        'notes':         job.notes,
        'lines': [
            {
                'name':     getattr(line, 'label', '') or line.service.name,
                'quantity': line.quantity,
                'pages':    line.pages,
                'specs':    line.specifications or {},
                'addon':    line.parent_id is not None,
            }
            for line in job.line_items.all()
        ],
        'files': _files(job),
        # Pays at the counter (24 Nov 2026): the code they'll say, printed
        # ahead or when they come, whether they're here, and what they owe.
        'counter': ({
            'code':        job.counter_code,
            'print_ahead': job.print_ahead,
            'here':        job.arrived_at.isoformat() if job.arrived_at else None,
            'shelved':     job.shelved_at.isoformat() if job.shelved_at else None,
            'with_cashier': job.status != Job.AWAITING_ARRIVAL,
            'owes':        str(job.estimated_cost or 0),
        } if job.counter_code else None),
    }


class DeskQueueView(APIView):
    """
    GET /api/v1/jobs/desk/queue/
    Front-desk work not yet done, soonest promise first. The screen splits
    it: waiting (nobody has taken it), mine, someone else's, held.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        branch, err = _branch_or_400(request)
        if err:
            return err
        now = timezone.now()
        problems = [
            {'value': value, 'label': label}
            for value, label in JobVerification.Outcome.choices
            if value != JobVerification.Outcome.PASSED
        ]
        return Response({
            'now':      now.isoformat(),
            'checks':   list(front_desk.DESK_CHECKS),
            'problems': problems,
            'jobs':     [_row(job, request.user, now) for job in front_desk.queue(branch)],
        })


class _DeskAction(APIView):
    """One job, one act. Subclasses say what the act is."""
    permission_classes = [IsAuthenticated]

    def act(self, request, job):
        raise NotImplementedError

    def post(self, request, pk):
        branch, err = _branch_or_400(request)
        if err:
            return err
        job = _desk_job(pk, branch)
        if job is None:
            return Response({'detail': 'Front-desk job not found.'}, status=status.HTTP_404_NOT_FOUND)
        try:
            detail = self.act(request, job)
        except (DeskRefused, CounterRefused) as e:
            return Response({'detail': str(e)}, status=status.HTTP_409_CONFLICT)
        except PermissionError as e:
            return Response({'detail': str(e)}, status=status.HTTP_403_FORBIDDEN)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        job = _desk_job(pk, branch)
        return Response({'success': True, 'detail': detail,
                         'job': _row(job, request.user, timezone.now()) if job else None})


class DeskTakeView(_DeskAction):
    """POST /api/v1/jobs/<pk>/desk/take/"""

    def act(self, request, job):
        front_desk.take(job.pk, job.branch, request.user)
        return f'{job.job_number} is yours.'


class DeskStartView(_DeskAction):
    """POST /api/v1/jobs/<pk>/desk/start/   Body: { signed_checks: ['file_opened', 'order_matches'] }"""

    def act(self, request, job):
        checks = [c for c in (request.data.get('signed_checks') or []) if isinstance(c, str)]
        front_desk.start(job, request.user, checks)
        return f'{job.job_number} checked and started.'


class DeskDoneView(_DeskAction):
    """POST /api/v1/jobs/<pk>/desk/done/"""

    def act(self, request, job):
        front_desk.finish(job, request.user)
        return f'{job.job_number} is done. The customer has been told.'


class DeskProblemView(_DeskAction):
    """POST /api/v1/jobs/<pk>/desk/problem/   Body: { outcome, note }"""

    def act(self, request, job):
        outcome = request.data.get('outcome')
        valid = [v for v, _ in JobVerification.Outcome.choices if v != JobVerification.Outcome.PASSED]
        if outcome not in valid:
            raise ValueError(f'Outcome must be one of: {", ".join(valid)}.')
        front_desk.hold(job, request.user, outcome, request.data.get('note', ''))
        return f'{job.job_number} is held until the customer answers.'


class DeskResumeView(_DeskAction):
    """POST /api/v1/jobs/<pk>/desk/resume/"""

    def act(self, request, job):
        front_desk.resume(job, request.user)
        return f'{job.job_number} is back in your hands.'


class DeskHereView(_DeskAction):
    """POST /api/v1/jobs/<pk>/desk/here/   A pays-at-the-counter customer came (or was found on the shelf)."""

    def act(self, request, job):
        counter_orders.here(job)
        return f'{job.job_number} is back on Work: they are here.'


class DeskCashierView(_DeskAction):
    """POST /api/v1/jobs/<pk>/desk/cashier/   Pays at the counter: on to the cashier, as a counter sale."""

    def act(self, request, job):
        counter_orders.send_to_cashier(job, request.user)
        return f'{job.job_number} is with the cashier: GHS {job.estimated_cost or 0:,.2f}.'


class DeskReplaceView(_DeskAction):
    """POST /api/v1/jobs/<id>/desk/replace/   a new job takes this waiting counter order's place"""
    def act(self, request, job):
        counter_orders.replace(job, request.user)
        return f'Code {job.counter_code} cancelled: the new job replaces it.'


class DeskWaitingForView(APIView):
    """
    GET /api/v1/jobs/desk/waiting-for/?customer=<id>
    Their orders waiting at the counter, for the job screen to say so before
    a second job is made for the same files (26 Nov 2026).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        branch, err = _branch_or_400(request)
        if err:
            return err
        try:
            customer = int(request.query_params.get('customer') or 0)
        except ValueError:
            customer = 0
        if not customer:
            return Response({'jobs': []})
        now = timezone.now()
        jobs = counter_orders.waiting_for(customer, branch).select_related('branch', 'customer')
        return Response({'jobs': [_row(job, request.user, now) for job in jobs]})


class DeskShelfView(APIView):
    """
    GET /api/v1/jobs/desk/shelf/?q=4821
    Waiting for collection: pays-at-the-counter orders not collected by
    closing, kept a week, found by code, name or number.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        branch, err = _branch_or_400(request)
        if err:
            return err
        now = timezone.now()
        jobs = counter_orders.shelf(branch, request.query_params.get('q', ''))
        return Response({
            'now':  now.isoformat(),
            'days': counter_orders.SHELF_DAYS,
            'jobs': [{**_row(job, request.user, now),
                      'cancels_on': (job.shelved_at + timedelta(days=counter_orders.SHELF_DAYS)).isoformat()}
                     for job in jobs],
        })
