"""
The public surface.

Every other endpoint in Octos requires a staff token. These do not: a
stranger pricing a banner has no account and should not need one to find
out what it costs.

What stands in for an account is a token on the order. The order number
is sequential — ORD-2026-00001 is one guess away from 00002 — so it can
never be what proves the order is yours. The token is returned once at
creation, required on every request afterwards, and is what the tracking
link carries.

Prices are never taken from the request. A total arriving from a browser
is a suggestion from a stranger; the server quotes every line again from
the specification, through the same function the counter uses.
"""

from decimal import Decimal

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.jobs.models import Service
from apps.jobs.pricing_engine import quote_line
from apps.storefront.models import OnlineOrder


def _order_or_404(order_number, token):
    """
    An order is reachable only by its own token. A wrong token and a
    wrong number give the same answer, so neither tells a stranger
    whether an order exists.
    """
    if not token:
        from django.http import Http404
        raise Http404
    return get_object_or_404(
        OnlineOrder, order_number=order_number, access_token=token,
    )


def _serialise(order):
    return {
        'order_number': order.order_number,
        'status': order.status,
        'branch': order.branch_id,
        'line_items': order.line_items,
        'total': f'{Decimal(order.total):.2f}',
        'fulfilment': order.fulfilment,
        'promised_for': order.promised_for,
        'is_paid': order.is_paid,
    }


class CatalogueView(APIView):
    """
    GET /api/v1/storefront/catalogue/

    What can be ordered, with the fields each service needs and the
    price it is quoted at. Browsing is not gated — anything that asks a
    stranger to identify themselves before they know what a job costs
    loses them.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        services = Service.objects.filter(is_active=True).order_by('category', 'name')
        return Response([
            {
                'id': s.id,
                'code': s.code,
                'name': s.name,
                'category': s.category,
                'unit': s.unit,
                'description': s.description,
                'spec_template': s.spec_template,
                'requires_file_upload': s.requires_file_upload,
            }
            for s in services
        ])


class OrderCreateView(APIView):
    """
    POST /api/v1/storefront/orders/

    Starts an order. It belongs to nobody: no branch, no customer, no
    payment. Most orders are abandoned at this point and that costs
    nothing.

    The token comes back once. There is no way to ask for it again.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        order = OnlineOrder.objects.create()
        payload = _serialise(order)
        payload['access_token'] = order.access_token
        return Response(payload, status=status.HTTP_201_CREATED)


class OrderDetailView(APIView):
    """
    GET   /api/v1/storefront/orders/<order_number>/?token=…
    PATCH /api/v1/storefront/orders/<order_number>/

    Reading and building. An order that has been paid for is closed to
    editing: the customer agreed to what they paid for, and the branch
    is working from it.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, order_number):
        order = _order_or_404(order_number, request.query_params.get('token'))
        return Response(_serialise(order))

    def patch(self, request, order_number):
        order = _order_or_404(order_number, request.data.get('token'))

        if not order.is_open:
            return Response(
                {'detail': (
                    'This order has been paid for and cannot be changed. '
                    'Call the branch if something needs correcting.'
                )},
                status=status.HTTP_409_CONFLICT,
            )

        if 'line_items' in request.data:
            priced, total, error = self._price(request.data['line_items'])
            if error:
                return Response({'detail': error}, status=status.HTTP_400_BAD_REQUEST)
            order.line_items = priced
            order.total = total

        if 'fulfilment' in request.data:
            order.fulfilment = request.data['fulfilment']
        if 'delivery_address' in request.data:
            order.delivery_address = request.data['delivery_address']

        order.save()
        return Response(_serialise(order))

    @staticmethod
    def _price(raw_lines):
        """
        Quote every line again, through the same function the counter
        uses. Whatever price the browser sent is ignored.
        """
        if not isinstance(raw_lines, list):
            return None, None, 'line_items must be a list.'

        priced = []
        total = Decimal('0.00')

        for line in raw_lines:
            try:
                service = Service.objects.get(pk=line.get('service'), is_active=True)
            except (Service.DoesNotExist, ValueError, TypeError):
                return None, None, f"Service {line.get('service')} is not available."

            quantity = int(line.get('quantity') or 1)
            specs = line.get('specifications') or {}

            quote = quote_line(
                service=service, branch=None,
                specifications=specs, quantity=quantity,
            )
            if not quote.get('success'):
                return None, None, quote.get('error', 'This line could not be priced.')

            priced.append({
                'service': service.id,
                'service_name': service.name,
                'quantity': quantity,
                'specifications': specs,
                'unit_price': str(quote.get('unit_price') or quote['total']),
                'total': str(quote['total']),
            })
            total += Decimal(str(quote['total']))

        return priced, total, None