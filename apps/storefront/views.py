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
import random
from apps.storefront.models import Lead, OnlineOrder
from apps.storefront.services.sms import send_sms
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.throttling import ScopedRateThrottle
from apps.jobs.models import Service
from apps.jobs.pricing_engine import quote_line



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
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'storefront'

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
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'storefront'

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
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'storefront'

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

DISCOUNT_RATE = Decimal('0.05')
DISCOUNT_THRESHOLD = Decimal('100.00')


class OrderIdentifyView(APIView):
    """
    POST /api/v1/storefront/orders/<order_number>/identify/

    A phone number and a first name. Asked for late: a stranger should
    know what a banner costs before being asked who they are.

    A number nobody has used becomes a lead. A number that has ordered
    before is recognised — and only challenged for a code if that
    person chose to set one. Being stopped at the door on the visit you
    came back is the wrong moment.
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'storefront_code'

    def post(self, request, order_number):
        order = _order_or_404(order_number, request.data.get('token'))

        if not order.is_open:
            return Response(
                {'detail': 'This order has been paid for.'},
                status=status.HTTP_409_CONFLICT,
            )

        phone = (request.data.get('phone') or '').strip()
        first_name = (request.data.get('first_name') or '').strip()
        if not phone or not first_name:
            return Response(
                {'detail': 'We need a phone number and a first name.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        lead = Lead.objects.filter(phone=phone).first()

        if lead and lead.has_code:
            given = (request.data.get('code') or '').strip()
            if not given or not lead.check_code(given):
                # The same answer whether no code was given or a wrong
                # one was: neither tells a stranger which it was.
                return Response(
                    {
                        'returning': True,
                        'code_required': True,
                        'detail': (
                            "You've ordered with us before. Enter your "
                            "code, or we can text you a new one."
                        ),
                    },
                    status=status.HTTP_401_UNAUTHORIZED,
                )

        returning = lead is not None
        if lead is None:
            lead = Lead.objects.create(phone=phone, first_name=first_name)

        order.lead = lead
        order.save(update_fields=['lead', 'updated_at'])

        return Response({
            'returning': returning,
            'code_required': False,
            'first_name': lead.first_name,
            'has_code': lead.has_code,
            # Worth offering only when there is something in it for them
            # and they have never had it.
            'discount_available': bool(
                not lead.has_code
                and not lead.code_discount_used
                and order.full_total >= DISCOUNT_THRESHOLD
            ),
        })


class OrderCodeView(APIView):
    """
    POST /api/v1/storefront/orders/<order_number>/code/

    Sets a code for the person on this order, and takes 5% off if the
    order is over GHS 100 and they have never had it.

    The code is generated rather than chosen — it is sent by text, and
    a code the customer picks is one they tell someone. It is hashed on
    the way in and never readable again: losing it means being sent a
    new one, which is the same experience and leaves nothing in the
    database worth stealing.
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'storefront'

    def post(self, request, order_number):
        order = _order_or_404(order_number, request.data.get('token'))

        if not order.is_open:
            return Response(
                {'detail': 'This order has been paid for.'},
                status=status.HTTP_409_CONFLICT,
            )

        if not order.lead_id:
            return Response(
                {'detail': 'Tell us who you are first.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        lead = order.lead
        code = _make_code(lead.first_name)
        lead.set_code(code)

        discount = Decimal('0.00')
        if not lead.code_discount_used and order.full_total >= DISCOUNT_THRESHOLD:
            # To the nearest cedi. Pesewas off a discount read as
            # arithmetic rather than as a gift.
            discount = (order.full_total * DISCOUNT_RATE).quantize(Decimal('1'))
            lead.code_discount_used = True
            order.discount_amount = discount
            order.discount_reason = 'Customer code — 5%'
            order.total = order.full_total - discount
            order.save(update_fields=[
                'discount_amount', 'discount_reason', 'total', 'updated_at',
            ])

        lead.save(update_fields=['code', 'code_discount_used', 'updated_at'])

        message = (
            f"Your Farhat code is {code}. Keep it — it brings up your "
            f"past orders next time."
        )
        if discount:
            message = (
                f"Your Farhat code is {code}. GHS {discount} off this "
                f"order. Keep it — it brings up your past orders next time."
            )
        send_sms(lead.phone, message)

        return Response({
            # Shown once. There is no way to ask for it again — a lost
            # code is replaced, not recovered.
            'code': code,
            'discount_amount': f'{discount:.2f}',
            'full_total': f'{Decimal(order.full_total):.2f}',
            'total': f'{Decimal(order.total):.2f}',
            'sent_to': lead.phone,
        })


def _make_code(first_name):
    """
    Three letters from their name and three characters after it, so it
    reads as theirs — AMA-4K2 rather than 7F2X9Q. People remember a
    thing that looks like it belongs to them.

    I and O and 1 and 0 are left out: a code read off a screen and typed
    back in should not turn on a glyph.
    """
    alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    stem = ''.join(c for c in (first_name or '').upper() if c.isalpha())[:3]
    stem = (stem or 'FAR').ljust(3, 'X')
    tail = ''.join(random.choice(alphabet) for _ in range(3))
    return f'{stem}-{tail}'