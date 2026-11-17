"""
Costs and discounts (17 Nov 2026).

GET  /api/v1/jobs/costs/                     what things cost, and a page from them
PUT  /api/v1/jobs/costs/                     change them (the Branch Manager or the owner)
PATCH /api/v1/jobs/services/<id>/cost/       what one unit of a service costs to make

GET  /api/v1/jobs/discounts/?job=<id>        the discount panel: price, savings, cost, floor
GET  /api/v1/jobs/discounts/?proforma=<id>
POST /api/v1/jobs/discounts/                 { job | proforma, new_total, reason }
GET  /api/v1/jobs/discounts/waiting/         price cuts waiting for the owner
POST /api/v1/jobs/discounts/<id>/approve/
POST /api/v1/jobs/discounts/<id>/decline/    { note }
"""
from decimal import Decimal, InvalidOperation

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.jobs.services import discounts
from apps.jobs.services.discounts import DiscountRefused

COST_FIELDS = ('toner_black_price', 'toner_black_pages', 'toner_colour_price', 'toner_colour_pages',
               'paper_box_price', 'paper_box_sheets', 'coverage', 'wear_percent', 'floor_multiple',
               'unknown_cost_limit')


def _costs_payload():
    from apps.jobs.models import CostSettings
    from apps.jobs.services.costing import page_costs

    s = CostSettings.current()
    c = page_costs(s)
    wear = 1 + c['wear']
    colour = (c['paper'] + c['colour']) * wear
    black = (c['paper'] + c['black']) * wear
    return {
        **{f: str(getattr(s, f)) for f in COST_FIELDS},
        'page': {
            'paper': f"{c['paper']:.2f}",
            'colour_toner': f"{c['colour']:.2f}",
            'black_toner': f"{c['black']:.2f}",
            'colour': f'{colour:.2f}',
            'black': f'{black:.2f}',
            'colour_floor': f'{colour * s.floor_multiple:.2f}',
            'black_floor': f'{black * s.floor_multiple:.2f}',
        },
    }


class CostSettingsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not discounts.may_discount(request.user):
            return Response({'detail': 'Only the Branch Manager or the owner sees costs.'}, status=403)
        return Response(_costs_payload())

    def put(self, request):
        from apps.jobs.models import CostSettings
        if not discounts.may_discount(request.user):
            return Response({'detail': 'Only the Branch Manager or the owner sets costs.'}, status=403)
        s = CostSettings.current()
        for field in COST_FIELDS:
            if field not in request.data:
                continue
            try:
                value = Decimal(str(request.data[field]))
            except (InvalidOperation, TypeError, ValueError):
                return Response({'detail': f'{field.replace("_", " ")} must be a number.'}, status=400)
            if value <= 0 and field != 'unknown_cost_limit':
                return Response({'detail': f'{field.replace("_", " ").capitalize()} must be more than zero.'},
                                status=400)
            setattr(s, field, int(value) if field.endswith(('_pages', '_sheets')) else value)
        s.save()
        return Response(_costs_payload())


class ServiceCostView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        from apps.jobs.api.serializers import ServiceSerializer
        from apps.jobs.models import Service

        if not discounts.may_discount(request.user):
            return Response({'detail': 'Only the Branch Manager or the owner sets costs.'}, status=403)
        service = Service.objects.filter(pk=pk).first()
        if service is None:
            return Response({'detail': 'Not found.'}, status=404)
        basis = request.data.get('cost_basis', service.cost_basis)
        if basis not in dict(Service.COST_BASIS):
            return Response({'detail': 'Choose what this costs: a colour page, a black and white page, '
                                       'a fixed amount, or not set.'}, status=400)
        try:
            size = Decimal(str(request.data.get('cost_size', service.cost_size)))
            amount = Decimal(str(request.data.get('cost_amount', service.cost_amount)))
        except (InvalidOperation, TypeError, ValueError):
            return Response({'detail': 'Size and amount must be numbers.'}, status=400)
        if size <= 0 or amount < 0:
            return Response({'detail': 'Size must be more than zero, and the amount zero or more.'}, status=400)
        service.cost_basis, service.cost_size, service.cost_amount = basis, size, amount
        service.save(update_fields=['cost_basis', 'cost_size', 'cost_amount', 'updated_at'])
        return Response(ServiceSerializer(service, context={'request': request}).data)


def _target_from(request, data):
    """The job or proforma asked about, if this person may see it."""
    from apps.jobs.models import Job, ProformaInvoice

    job_id, proforma_id = data.get('job'), data.get('proforma')
    if job_id:
        target = Job.objects.filter(pk=job_id).select_related('discount_by').first()
    elif proforma_id:
        target = ProformaInvoice.objects.filter(pk=proforma_id).select_related('discount_by').first()
    else:
        return None
    if target is None:
        return None
    if not discounts.is_owner(request.user) and target.branch_id != getattr(request.user, 'branch_id', None):
        return None
    return target


class DiscountView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not discounts.may_discount(request.user):
            return Response({'detail': 'Only the Branch Manager or the owner can lower a price.'}, status=403)
        target = _target_from(request, request.query_params)
        if target is None:
            return Response({'detail': 'Not found.'}, status=404)
        return Response(discounts.summary(target))

    def post(self, request):
        target = _target_from(request, request.data)
        if target is None:
            return Response({'detail': 'Not found.'}, status=404)
        from apps.jobs.models import Job
        kind = {'job': target} if isinstance(target, Job) else {'proforma': target}
        try:
            cut = discounts.lower(request.user, request.data.get('new_total'), request.data.get('reason'), **kind)
        except DiscountRefused as refused:
            return Response({'detail': str(refused)}, status=400)
        target.refresh_from_db()
        return Response({'status': cut.status, 'summary': discounts.summary(target)},
                        status=201 if cut.status == cut.Status.APPLIED else 202)


class DiscountWaitingView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not discounts.is_owner(request.user):
            return Response({'detail': 'Only the owner decides these.'}, status=403)
        return Response(discounts.waiting())


class DiscountDecisionView(APIView):
    permission_classes = [IsAuthenticated]
    approve = True

    def post(self, request, pk):
        try:
            if self.approve:
                cut = discounts.approve(request.user, pk)
            else:
                cut = discounts.decline(request.user, pk, request.data.get('note', ''))
        except DiscountRefused as refused:
            return Response({'detail': str(refused)}, status=400)
        return Response({'status': cut.status})
