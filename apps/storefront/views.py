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
from apps.storefront.models import Lead, OnlineOrder, OrderFile, PaystackEvent
from apps.storefront.services.sms import send_sms
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.throttling import ScopedRateThrottle
from apps.jobs.models import Service
from apps.jobs.pricing_engine import quote_line
import hashlib
import hmac
import json
import logging
from apps.storefront.services import paystack
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.parsers import MultiPartParser
from apps.jobs.services.file_checks import check_file
from apps.jobs.services.file_metadata import extract
from rest_framework.parsers import JSONParser, MultiPartParser
from apps.storefront.services.fees import split_payment
from apps.production.capability import assess

logger = logging.getLogger(__name__)


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
            # The branch was chosen against the old size. A branch that
            # could make a 36-inch banner may not be able to make a
            # 90-inch one, so the choice is made again rather than
            # assumed to still hold.
            order.branch = None

        if 'branch' in request.data:
            branch, error = _choose_branch(order, request.data['branch'])
            if error:
                return Response({'detail': error},
                                status=status.HTTP_400_BAD_REQUEST)
            order.branch = branch

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

"""
Append to apps/storefront/views.py.

Imports needed at the top, alongside the ones already there:

    import hashlib
    import hmac
    import json
    import logging
    from django.conf import settings
    from django.db import IntegrityError, transaction
    from django.utils import timezone
    from apps.storefront.services.fees import split_payment

    logger = logging.getLogger(__name__)
"""


class PaystackWebhookView(APIView):
    """
    POST /api/v1/storefront/webhook/paystack/

    What marks an order paid. Not the customer returning to the page: a
    customer who closes the tab after paying has still paid, and one who
    reaches the success page without paying has not.

    It does the least it can — record the event, mark the order, return.
    Converting to a job, choosing a branch and writing a receipt all
    happen elsewhere. Paystack retries anything slow or failed, and a
    webhook that tries to do everything is one that fails halfway
    through and gets retried into a mess.

    Three things it will not skip:

      the signature  without it, anyone who finds this URL can mark
                     orders paid
      the amount     the event says what was paid; if that is not what
                     the order says, nobody should be printing anything
      the duplicate  Paystack retries, and money counted twice is money
                     the books cannot explain
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    # No throttle. Refusing Paystack's retries would only make it retry
    # harder, and the signature is what actually keeps strangers out.
    throttle_classes = []

    def post(self, request):
        raw = request.body
        if not self._signed(raw, request.headers.get('x-paystack-signature', '')):
            logger.warning('Paystack webhook with a bad signature')
            return Response(
                {'detail': 'Bad signature.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        try:
            body = json.loads(raw)
        except ValueError:
            return Response({'detail': 'Unreadable body.'},
                            status=status.HTTP_400_BAD_REQUEST)

        event_type = body.get('event', '')
        data = body.get('data') or {}
        reference = (data.get('reference') or '').strip()

        # Anything we do not act on is still acknowledged. Refusing would
        # make Paystack retry an event nothing is waiting for.
        if event_type != 'charge.success' or not reference:
            return Response({'status': 'ignored'})

        order = OnlineOrder.objects.filter(payment_reference=reference).first()
        if order is None:
            # Acknowledged, not retried: this will never match anything.
            logger.warning('Paystack event for unknown reference %s', reference)
            return Response({'status': 'no matching order'})

        # Paystack sends the smallest unit — pesewas.
        paid = (Decimal(str(data.get('amount') or 0)) / Decimal('100')).quantize(
            Decimal('0.01')
        )
        if paid != order.total:
            logger.error(
                'Paystack amount %s does not match order %s at %s',
                paid, order.order_number, order.total,
            )
            return Response(
                {'detail': 'Amount does not match the order.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            with transaction.atomic():
                # The write is the check. A "have we seen this?" lookup
                # followed by a write would let two simultaneous
                # deliveries both pass; the unique constraint lets only
                # one through, and the refusal is how we know.
                PaystackEvent.objects.create(
                    reference=reference,
                    event_type=event_type,
                    provider_id=str(data.get('id') or ''),
                    amount_minor=int(data.get('amount') or 0),
                    channel=data.get('channel') or '',
                    payload=body,
                    order=order,
                )
        except IntegrityError:
            return Response({'status': 'already recorded'})

        gross, fee, net = split_payment(order.total)
        order.payment_fee = fee
        order.net_received = net
        order.paid_at = timezone.now()
        order.status = OnlineOrder.Status.PAID
        order.save(update_fields=[
            'payment_fee', 'net_received', 'paid_at', 'status', 'updated_at',
        ])

        if order.lead_id:
            lead = order.lead
            lead.order_count = lead.order_count + 1
            lead.last_ordered_at = timezone.now()
            lead.save(update_fields=[
                'order_count', 'last_ordered_at', 'updated_at',
            ])

        logger.info(
            'Order %s paid: gross %s, fee %s, net %s',
            order.order_number, gross, fee, net,
        )
        return Response({'status': 'recorded'})

    @staticmethod
    def _signed(raw, given):
        """
        HMAC-SHA512 of the raw body with the secret key, which is what
        Paystack signs with. Compared in constant time, so the
        comparison itself gives nothing away.
        """
        secret = getattr(settings, 'PAYSTACK_SECRET_KEY', '')
        if not secret or not given:
            return False
        expected = hmac.new(secret.encode(), raw, hashlib.sha512).hexdigest()
        return hmac.compare_digest(expected, given)

"""
Append this class to apps/storefront/views.py.

It needs one more import at the top, alongside the others:

    from apps.storefront.services import paystack

Imported as a module rather than as its functions, so a test can replace
`paystack.initialise` and the view picks up the replacement.
"""


class OrderPayView(APIView):
    """
    POST /api/v1/storefront/orders/<order_number>/pay/

    Hands the order to Paystack and returns somewhere to send the
    customer. Nothing about the payment itself happens on our pages:
    cards, mobile money and bank all live on their checkout.

    This does not mark anything paid. The customer arriving at the
    success page proves nothing — they may have closed the tab, or
    reached it without paying. The webhook is what settles that.
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'storefront'

    def post(self, request, order_number):
        order = _order_or_404(order_number, request.data.get('token'))

        if order.is_paid or order.status == OnlineOrder.Status.PAID:
            return Response(
                {'detail': 'This order has already been paid for.'},
                status=status.HTTP_409_CONFLICT,
            )

        if not order.lead_id:
            return Response(
                {'detail': 'Tell us who you are first.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not order.branch_id:
            return Response(
                {'detail': 'Choose where you’d like this made.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if order.total <= 0:
            return Response(
                {'detail': 'There is nothing on this order yet.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        missing = _artwork_missing(order)
        if missing:
            return Response({'detail': missing}, status=status.HTTP_400_BAD_REQUEST)

        # Paystack wants an email. Most of our customers give a phone
        # number and nothing else, so one is derived from it — the
        # receipt that matters is the one we send by SMS.
        email = (request.data.get('email') or '').strip()
        if not email:
            digits = ''.join(c for c in order.lead.phone if c.isdigit())
            email = f'{digits}@customers.farhatpress.com'

        result = paystack.initialise(
            reference=order.order_number,
            amount_minor=paystack.to_minor(order.total),
            email=email,
            callback_url=request.data.get('callback_url') or None,
            metadata={
                'order_number': order.order_number,
                'customer': order.lead.first_name,
                'phone': order.lead.phone,
            },
        )

        if not result.get('success'):
            # The order is left exactly as it was, so the customer can
            # try again without rebuilding anything.
            return Response(
                {'detail': result.get('error', 'Could not start the payment.')},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        order.payment_reference = result.get('reference') or order.order_number
        order.status = OnlineOrder.Status.AWAITING_PAYMENT
        order.save(update_fields=[
            'payment_reference', 'status', 'updated_at',
        ])

        return Response({
            'authorization_url': result.get('authorization_url'),
            'reference': order.payment_reference,
            'amount': f'{Decimal(order.total):.2f}',
        })

"""
Append this class to apps/storefront/views.py.

It needs these imports at the top, alongside the ones already there:

    from rest_framework.parsers import MultiPartParser
    from apps.storefront.models import Lead, OnlineOrder, OrderFile, PaystackEvent
    from apps.jobs.services.file_checks import check_file
    from apps.jobs.services.file_metadata import extract
"""


# A hard ceiling, refused before anything is read. Print artwork is
# large, and this is generous for one file — but not a door left open.
MAX_UPLOAD_BYTES = 40 * 1024 * 1024


class OrderFileView(APIView):
    """
    POST /api/v1/storefront/orders/<order_number>/file/
    GET  /api/v1/storefront/orders/<order_number>/file/?token=…

    Artwork, measured and judged against what was ordered.

    The verdict belongs to the pairing, not to the file: 1080 pixels is
    good artwork on a business card and unprintable across six feet. So
    the GET rejudges rather than returning what was stored — a customer
    who makes their banner bigger after uploading must be told.

    Refuse blocks the order. Warn proceeds, and the acceptance is kept,
    so the coordinator sees the customer was told rather than finding
    the problem himself.
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'storefront'
    # Multipart for the upload, JSON for the acceptance — that one
    # carries no file, and refusing it over a content type is a 415 the
    # customer reads as the page being broken.
    parser_classes = [MultiPartParser, JSONParser]

    def post(self, request, order_number):
        order = _order_or_404(order_number, request.data.get('token'))

        if not order.is_open:
            return Response(
                {'detail': 'This order has been paid for.'},
                status=status.HTTP_409_CONFLICT,
            )

        upload = request.FILES.get('file')
        if not upload:
            return Response({'detail': 'No file was sent.'},
                            status=status.HTTP_400_BAD_REQUEST)

        if upload.size > MAX_UPLOAD_BYTES:
            return Response(
                {'detail': (
                    'That file is too large to send over the web. Bring it '
                    'to the branch on a flash drive, or send a smaller export.'
                )},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # One file per order. A customer who sends better artwork has
        # replaced the first, and the floor should never have to guess
        # which of two to print.
        for existing in order.files.all():
            existing.file.delete(save=False)
            existing.delete()

        record = OrderFile.objects.create(
            order=order,
            file=upload,
            original_filename=upload.name,
            content_type=upload.content_type or '',
        )

        # Measures and saves. Never raises: a file that cannot be read is
        # still a file that arrived, and the upload must not fail because
        # the bytes were odd.
        extract(record)
        record.refresh_from_db()

        verdict = _judge(order, record)
        record.verdict = verdict['verdict']
        record.checks = verdict['checks']
        record.save(update_fields=['verdict', 'checks', 'updated_at'])

        return Response(_file_payload(record), status=status.HTTP_201_CREATED)

    def get(self, request, order_number):
        order = _order_or_404(order_number, request.query_params.get('token'))
        record = order.files.first()
        if record is None:
            return Response({'detail': 'No file on this order yet.'},
                            status=status.HTTP_404_NOT_FOUND)

        # Judged again, not read back. The order may have changed size
        # since the file arrived.
        verdict = _judge(order, record)
        if verdict['verdict'] != record.verdict:
            record.verdict = verdict['verdict']
            record.checks = verdict['checks']
            record.save(update_fields=['verdict', 'checks', 'updated_at'])

        return Response(_file_payload(record))

    def patch(self, request, order_number):
        """Accepting a warning, so the order can carry on."""
        order = _order_or_404(order_number, request.data.get('token'))
        record = order.files.first()
        if record is None:
            return Response({'detail': 'No file on this order yet.'},
                            status=status.HTTP_404_NOT_FOUND)

        record.warning_accepted = bool(request.data.get('warning_accepted'))
        record.save(update_fields=['warning_accepted', 'updated_at'])
        return Response(_file_payload(record))


def _judge(order, record):
    """
    The file against the line it belongs to.

    With no line yet, only the file itself can be judged — format and
    whether it opens. The resolution check needs a size to be judged
    against, and inventing one would answer a question nobody asked.
    """
    line = (order.line_items or [None])[0]
    specs = (line or {}).get('specifications') or {}

    width_in = specs.get('width_in')
    height_in = specs.get('height_in')

    return check_file(
        metadata_state=record.metadata_state,
        content_type=record.content_type,
        width_px=record.width_px,
        height_px=record.height_px,
        width_mm=record.width_mm,
        height_mm=record.height_mm,
        page_count=record.page_count,
        colour_mode=record.colour_mode,
        pdf_images=record.pdf_images,
        ordered_width_in=width_in,
        ordered_height_in=height_in,
        ordered_pages=specs.get('pages'),
    )


def _file_payload(record):
    return {
        'filename': record.original_filename,
        'size_kb': round(record.size_bytes / 1024, 1) if record.size_bytes else None,
        'width_px': record.width_px,
        'height_px': record.height_px,
        'page_count': record.page_count,
        'verdict': record.verdict,
        'checks': record.checks,
        'warning_accepted': record.warning_accepted,
    }

def _artwork_missing(order):
    """
    Whether this order still needs a file before it can be paid for.

    A branch cannot print what it has not been sent. Taking the money
    first means an order reaches the floor with nothing on it, and the
    conversation that follows starts with the customer already out of
    pocket.

    A refused file is not a file: we have already said we cannot print
    it. A warned one is, as long as the customer said carry on — that
    acceptance is on the record for the coordinator to see.
    """
    needs_file = False
    for line in (order.line_items or []):
        service = Service.objects.filter(pk=line.get('service')).first()
        if service and service.requires_file_upload:
            needs_file = True
            break

    if not needs_file:
        return None

    record = order.files.first()
    if record is None:
        return 'Send us your artwork before paying.'
    if record.verdict == 'refuse':
        return 'We can’t print the file you sent. Send another before paying.'
    if record.verdict == 'warn' and not record.warning_accepted:
        return 'Have a look at the note on your file before paying.'
    return None

"""
Append this class and its two helpers to apps/storefront/views.py.

The import it needs at the top, alongside the others:

    from apps.production.capability import assess
"""


# 25.4mm to the inch.
MM_PER_INCH = Decimal('25.4')


class OrderBranchesView(APIView):
    """
    GET /api/v1/storefront/orders/<order_number>/branches/?token=…

    Where this order could be made, and when each branch would finish.

    The customer chooses. Two branches — one ready at four across town,
    one tomorrow round the corner — and only they know which matters.
    So both travel with the answer and neither is picked for them.

    A branch appears only when it can genuinely do the work today: it
    has the machine, the machine is running, and the material fits.
    Where none can, the reasons come back instead of an empty list,
    because 'no branch can print a banner that wide' tells a customer
    what to change and silence does not.
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'storefront'

    def get(self, request, order_number):
        order = _order_or_404(order_number, request.query_params.get('token'))

        lines = _prediction_lines(order)
        if not lines:
            return Response(
                {'detail': 'There is nothing on this order yet.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        location = None
        lat = request.query_params.get('latitude')
        lon = request.query_params.get('longitude')
        if lat and lon:
            location = {'latitude': lat, 'longitude': lon}

        result = assess(
            lines,
            width_mm=_roll_width_mm(order),
            customer_location=location,
        )

        return Response({
            'options': [
                {
                    'branch_id': option['branch_id'],
                    'branch_name': option['branch_name'],
                    'branch_code': option['branch_code'],
                    'address': option['address'],
                    'ready_at': option['ready_at'],
                    'minutes': round(option['minutes']),
                    'is_next_day': option['is_next_day'],
                    'confidence': option['confidence'],
                    'distance_m': option['distance_m'],
                }
                for option in result['options']
            ],
            'refusals': [
                {'branch_name': r['branch_name'], 'reason': r['reason']}
                for r in result['refusals']
            ],
        })


def _prediction_lines(order):
    """
    The order's lines in the shape the prediction takes:
    (service, quantity, pieces).

    For area-priced work the quantity is the area, because that is what
    the per-unit figure is counted in — minutes per square foot.
    """
    lines = []
    for line in (order.line_items or []):
        service = Service.objects.filter(pk=line.get('service')).first()
        if service is None:
            continue

        pieces = int(line.get('quantity') or 1)
        specs = line.get('specifications') or {}

        unit = (service.unit or '').upper().replace('PER_', '')
        if unit in ('SQFT', 'SQCM', 'SQM'):
            width = specs.get('width_in')
            height = specs.get('height_in')
            if width and height:
                area = (Decimal(str(width)) * Decimal(str(height))) / Decimal('144')
            else:
                area = Decimal('1')
            lines.append((service, float(area), pieces))
        else:
            lines.append((service, pieces, int(specs.get('pages') or 1)))

    return lines


def _roll_width_mm(order):
    """
    How much roll width this order needs.

    The shorter side, not the longer one. A banner is fed with its
    short side across the roll and its length running off it — a
    168 × 36 banner needs 36 inches of width, not 168. Reading the
    larger number would refuse nearly every banner we sell.

    None where no line is sized, which leaves the width check out of
    it rather than inventing a constraint.
    """
    widest = None

    for line in (order.line_items or []):
        specs = line.get('specifications') or {}
        width = specs.get('width_in')
        height = specs.get('height_in')
        if not (width and height):
            continue

        across = min(Decimal(str(width)), Decimal(str(height))) * MM_PER_INCH
        widest = across if widest is None else max(widest, across)

    return float(widest) if widest is not None else None

def _choose_branch(order, branch_id):
    """
    The customer's pick, checked again on the way in.

    The options were right when they were drawn, and a machine can go
    down between seeing the list and tapping it. Trusting the id alone
    would let an order land on a floor that cannot make it.
    """
    from apps.organization.models import Branch
    from apps.production.capability import branch_options

    branch = Branch.objects.filter(pk=branch_id, is_active=True).first()
    if branch is None:
        return None, 'That branch is not one we can send this to.'

    lines = _prediction_lines(order)
    if not lines:
        return None, 'There is nothing on this order yet.'

    able = branch_options(lines, width_mm=_roll_width_mm(order))
    if not any(option['branch_id'] == branch.id for option in able):
        return None, (
            f'{branch.name} can’t make this one right now. '
            f'Pick another branch.'
        )

    return branch, None