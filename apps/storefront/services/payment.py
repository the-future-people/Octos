"""
Taking money for an online order: one path, used by the storefront's pay
button and by Octos on WhatsApp.

Moved out of the storefront's view (Nov 2026) so the two can't drift:
the checks before any money is taken, the email Paystack insists on,
the retry-safe reference, the promise worked out at the moment of
payment, and the order marked as waiting. Nothing here marks an order
paid; only the webhook does that.
"""
from decimal import Decimal


class PaymentRefused(Exception):
    """Why a payment can't start, and the HTTP status the storefront answers with."""

    def __init__(self, detail, status=400):
        super().__init__(detail)
        self.detail = detail
        self.status = status


def artwork_missing(order):
    """
    Whether this order still needs a file before it can be paid for.

    A branch cannot print what it has not been sent. Taking the money
    first means an order reaches the floor with nothing on it, and the
    conversation that follows starts with the customer already out of
    pocket.

    A refused file is not a file: we have already said we cannot print
    it. A warned one is, as long as the customer said carry on; that
    acceptance is on the record for the coordinator to see.
    """
    from apps.jobs.models import Service

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


def start_payment(order, email='', callback_url=None):
    """
    Start a Paystack payment for an order. Returns the checkout link, the
    reference and the amount; raises PaymentRefused when it can't start.
    """
    from apps.storefront.models import OnlineOrder
    from apps.storefront.services import paystack
    from apps.storefront.services.conversion import promise_for

    if order.is_paid or order.status == OnlineOrder.Status.PAID:
        raise PaymentRefused('This order has already been paid for.', 409)
    if not order.lead_id:
        raise PaymentRefused('Tell us who you are first.')
    if not order.branch_id:
        raise PaymentRefused('Choose where you’d like this made.')
    if order.total <= 0:
        raise PaymentRefused('There is nothing on this order yet.')
    missing = artwork_missing(order)
    if missing:
        raise PaymentRefused(missing)

    # Paystack wants an email. Most of our customers give a phone
    # number and nothing else, so one is derived from it; the
    # receipt that matters is the one we send by SMS.
    if not email:
        digits = ''.join(c for c in order.lead.phone if c.isdigit())
        email = f'{digits}@customers.farhatpress.com'

    reference = order.next_payment_reference()
    if reference is None:
        raise PaymentRefused('This order has already been paid.')

    # The promise, worked out now: the moment the customer pays is the
    # moment it is made. A cart can sit for days, and a time worked out
    # on Monday means nothing on Thursday.
    promise = promise_for(order)
    if promise is not None:
        order.promised_for = promise
        order.save(update_fields=['promised_for'])

    result = paystack.initialise(
        # Its own reference, so backing out of one attempt does not
        # stop the next. Paystack never forgets a reference it has
        # seen, and the order number alone would be seen once.
        reference=reference,
        amount_minor=paystack.to_minor(order.total),
        email=email,
        callback_url=callback_url,
        metadata={
            'order_number': order.order_number,
            'customer': order.lead.first_name,
            'phone': order.lead.phone,
        },
    )
    if not result.get('success'):
        # The order is left exactly as it was, so the customer can
        # try again without rebuilding anything.
        raise PaymentRefused(result.get('error', 'Could not start the payment.'), 502)

    order.payment_reference = result.get('reference') or order.order_number
    order.status = OnlineOrder.Status.AWAITING_PAYMENT
    order.save(update_fields=['payment_reference', 'status', 'updated_at'])

    return {
        'authorization_url': result.get('authorization_url'),
        'reference': order.payment_reference,
        'amount': f'{Decimal(order.total):.2f}',
    }