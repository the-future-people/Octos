"""
A paid order becoming work the floor can see.

Everything before this is the customer's side: a cart, a price, a
payment. This is where it crosses into the shop — a job on the board, a
receipt in the books, artwork the press can open.

Three things it is careful about.

**Once only.** Paystack retries, a task can run twice, and a sweep runs
behind the task. Two jobs for one payment means the floor prints a
banner twice and nobody notices until collection.

**Nobody took it in.** A counter job has an attendant who received it
and a cashier who took the money. An online order has neither, and the
fields stay empty rather than naming an invented member of staff. The
screen says "Print Octos" where a name would go; the database says what
is true.

**The money waits for a sheet.** A payment at twenty to midnight on a
Sunday is real, and the job should be on the board in the morning — but
it cannot land on a sheet that does not exist, and it must never land
on one a manager has already counted and signed off.
"""

import logging

from django.db import transaction
from django.utils import timezone

from apps.storefront.services.sms import send_sms

logger = logging.getLogger(__name__)


def convert(order):
    """
    Make the job. Returns it, or the one that already exists, or None
    where the order is not ready.

    Safe to call twice: the second call finds the job the first made.
    """
    from apps.finance.models import DailySalesSheet
    from apps.jobs.models import Job

    if order.job_id:
        return order.job

    if not order.is_paid and order.status != order.Status.PAID:
        logger.info('Not converting %s — not paid', order.order_number)
        return None

    if not order.branch_id:
        # Nowhere to make it. Payment refuses an order with no branch,
        # so this should not happen — but a job on no floor is worse
        # than a conversion that waits for someone to look at it.
        logger.error(
            'Cannot convert %s — no branch on the order', order.order_number,
        )
        return None
    sheet = _open_sheet(order.branch)

    with transaction.atomic():
        # Look again under a lock. The check at the top reads the copy of
        # the order this caller was handed; two callers converting at the
        # same moment (the worker and a customer's confirmation page, a
        # retry and the sweep) would both see no job there and both make
        # one. Whoever takes the lock second finds the first one's job.
        locked = type(order).objects.select_for_update().get(pk=order.pk)
        if locked.job_id:
            return locked.job

        job = Job.objects.create(
            branch=order.branch,
            customer=_customer_and_link(order),
            daily_sheet=sheet,
            # Always production. Online work is paid for before it is
            # made, and only the production flow has a way to say
            # "ready" — the instant flow goes straight from owing to
            # finished, which no unmade online job can honestly be.
            job_type=Job.PRODUCTION,
            title=_title(order),
            # Where a cashier would have left it once the money was in.
            # PENDING_PAYMENT here put every paid online job in the
            # cashier's queue and held the day sheet open as a debt.
            status=Job.PAID,
            estimated_cost=order.total,
            # Nobody. An online order has no attendant, and a fake one
            # would turn up in staff lists for years.
            intake_by=None,
            # Which puts it in the coordinator's arrivals queue rather
            # than straight onto the floor. Nobody has looked at this
            # artwork yet, and the check before a machine runs is the
            # whole point of that column.
            intake_channel=Job.ONLINE,
            # SETTLED, not PAID — PAID is not a value on this axis.
            # choices are not enforced on create(), so the wrong word
            # went in silently, and an attendant cannot release a job
            # that is not SETTLED: every online customer would have
            # been turned away at collection.
            payment_state=Job.Payment.SETTLED,
            work_state='RECEIVED',
            handover_state='AWAITING_COLLECTION',
            deposit_percentage=100,
            amount_paid=order.total,
            # The promise the customer paid against. An order that somehow
            # arrives without one gets one now: no online job is left with
            # nothing to be late against.
            estimated_ready_at=order.promised_for or promise_for(order),
            notes=f'Ordered online — {order.order_number}',
        )

        _carry_lines(order, job)
        _write_receipt(order, job, sheet)

        order.job = job
        order.status = order.Status.CONVERTED
        order.save(update_fields=['job', 'status', 'updated_at'])

    # Outside the transaction deliberately. A file that will not copy
    # must not cost the customer their job — but a database error
    # inside an atomic block poisons it, so swallowing one in there
    # rescues nothing and fails somewhere more confusing. Out here the
    # job and its receipt are already committed, and the coordinator
    # can ask for the artwork again.
    _carry_artwork(order, job)
    _tell_the_customer(order)

    logger.info(
        'Converted %s into job %s', order.order_number, job.job_number,
    )
    return job


def catch_up(branch):
    """
    Attach work that was made while the branch was shut.

    Called when a sheet opens. An online job created overnight has no
    sheet, and its money is not counted anywhere until it gets one —
    the sheet's totals are summed from the receipts on it.

    Returns how many were attached, so the task can be seen to be
    working rather than merely scheduled.
    """
    from apps.finance.models import Receipt
    from apps.jobs.models import Job

    sheet = _open_sheet(branch)
    if sheet is None:
        return 0

    waiting = Job.objects.filter(
        branch=branch,
        daily_sheet__isnull=True,
        online_order__isnull=False,
    )

    moved = 0
    for job in waiting:
        with transaction.atomic():
            job.daily_sheet = sheet
            job.save(update_fields=['daily_sheet', 'updated_at'])

            Receipt.objects.filter(
                job=job, daily_sheet__isnull=True,
            ).update(daily_sheet=sheet)

            moved += 1
            logger.info(
                'Attached %s to sheet %s — paid while the branch was shut',
                job.job_number, sheet.pk,
            )

    return moved


def _open_sheet(branch):
    """
    Today's sheet, if it is open.

    None where there is none, or where it has been closed. A manager
    who has counted the drawer and signed off should never find the
    total has moved since — money that arrives after that waits for
    the next sheet rather than reopening a settled day.
    """
    from apps.finance.models import DailySalesSheet

    return DailySalesSheet.objects.filter(
        branch=branch,
        date=timezone.localdate(),
        status=DailySalesSheet.Status.OPEN,
    ).first()


def _customer_for(order):
    """
    Who this is for.

    Somebody who has walked in before is the same person online, and
    two records of them is how a customer's history splits in half —
    the counter sees one past and the website another.
    """
    from apps.customers.models import CustomerProfile

    if not order.lead_id:
        return None

    lead = order.lead

    # The lead's own customer first; then anyone with this number, on
    # either of their numbers, however it was stored. An exact match
    # missed customers stored as 0244... once leads were +233..., and
    # made a second record of the same person.
    existing = lead.customer if lead.customer_id else None
    if existing is None:
        from django.db.models import Q
        from apps.core.phones import lookup_forms
        forms = lookup_forms(lead.phone)
        existing = (CustomerProfile.objects
                    .filter(Q(phone__in=forms) | Q(secondary_phone__in=forms))
                    .order_by('created_at').first())
    if existing is not None:
        return existing

    # A first name and a number is all an online order has. The counter
    # asks for more when they come in, and the record fills out then —
    # a profile that exists is worth more than a complete one that
    # does not.
    return CustomerProfile.objects.create(
        first_name=lead.first_name,
        phone=lead.phone,
        customer_type='INDIVIDUAL',
        branch=order.branch,
    )

def _title(order):
    """
    What the coordinator reads on the board.

    The services themselves, because "Online order" tells whoever is
    looking at the board nothing about what to make.
    """
    names = [
        line.get('service_name') for line in (order.line_items or [])
        if line.get('service_name')
    ]
    if not names:
        return f'Online order {order.order_number}'
    if len(names) == 1:
        return names[0]
    return f'{names[0]} and {len(names) - 1} more'


def _carry_lines(order, job):
    """
    The order's lines become the job's, priced as they were quoted.

    Not re-priced. The customer paid what they were shown, and a rule
    that changed overnight must not change what they bought.
    """
    from apps.jobs.models import JobLineItem, Service
    from decimal import Decimal

    position = 0
    for line in order.line_items or []:
        service = Service.objects.filter(pk=line.get('service')).first()
        if service is None:
            logger.error(
                'Line on %s names service %s, which is gone',
                order.order_number, line.get('service'),
            )
            continue

        specs = line.get('specifications') or {}

        # The piece itself, at its own price: add-ons are priced apart.
        piece = JobLineItem.objects.create(
            job=job,
            service=service,
            quantity=line.get('quantity') or 1,
            pages=specs.get('pages') or 1,
            specifications=specs,
            unit_price=Decimal(str(line.get('unit_price') or '0')),
            line_total=Decimal(str(line.get('base_total') or line.get('total') or '0')),
            position=position,
        )
        position += 1

        # Each add-on its own priced line, attached to the piece it finishes.
        for extra in line.get('addons') or []:
            addon = Service.objects.filter(pk=extra.get('service')).first()
            if addon is None:
                logger.error(
                    'Add-on on %s names service %s, which is gone',
                    order.order_number, extra.get('service'),
                )
                continue
            JobLineItem.objects.create(
                job=job,
                service=addon,
                parent=piece,
                quantity=extra.get('quantity') or 1,
                pages=1,
                # What Octos chose for it, kept for the floor: the binder
                # needs to know it is an 8mm ring.
                specifications={'detail': extra['detail']} if extra.get('detail') else {},
                unit_price=Decimal(str(extra.get('unit_price') or '0')),
                line_total=Decimal(str(extra.get('total') or '0')),
                position=position,
            )
            position += 1


def _carry_artwork(order, job):
    """
    The artwork, with the verdict the customer was shown.

    The file is copied rather than moved, so the order keeps its own
    record of what was sent — a customer asking what they uploaded
    should get an answer even after the job is done.

    The verdict travels because the coordinator should see what the
    customer was told. A file accepted with a warning is not the same
    as one that passed, and the floor knowing the difference is how a
    soft print stops being a surprise.
    """
    from apps.jobs.models import JobFile

    for record in order.files.all():
        try:
            job_file = JobFile(
                job=job,
                original_filename=record.original_filename,
                size_bytes=record.size_bytes,
                content_type=record.content_type,
                metadata_state=record.metadata_state,
                page_count=record.page_count,
                width_px=record.width_px,
                height_px=record.height_px,
                width_mm=record.width_mm,
                height_mm=record.height_mm,
                dpi=record.dpi,
                colour_mode=record.colour_mode,
                pdf_images=record.pdf_images,
                verdict=record.verdict,
                checks=record.checks,
            )
            job_file.file.save(
                record.original_filename, record.file, save=False,
            )
            job_file.save()
        except Exception:
            # Swallowed on purpose, and safe to swallow because this
            # runs outside the transaction. The job and its receipt
            # are already committed; a file that will not copy is
            # something the coordinator can ask for again.
            logger.error(
                'Could not carry artwork %s onto %s',
                record.pk, job.job_number, exc_info=True,
            )


def _write_receipt(order, job, sheet):
    """
    The money, in the books.

    Through the receipt engine rather than by hand: it owns the
    numbering, the tax arithmetic and the customer snapshot, and a
    second implementation of any of those would drift from the
    counter's within a month.

    No cashier. Nobody counted this money — Paystack did.
    """
    from apps.finance.receipt_engine import ReceiptEngine
    from decimal import Decimal

    try:
        ReceiptEngine(order.branch).issue(
            job=job,
            cashier=None,
            daily_sheet=sheet,
            payment_method='ONLINE',
            amount_paid=order.total,
            balance_due=Decimal('0.00'),
            customer_phone=order.lead.phone if order.lead_id else '',
        )
    except Exception:
        # Raised inside the transaction, so the whole conversion rolls
        # back. A job with no receipt is money the books cannot see,
        # and finding that later is worse than converting late.
        logger.error(
            'Could not write a receipt for %s', order.order_number,
            exc_info=True,
        )
        raise

def _tell_the_customer(order):
    """
    The text that says it worked.

    Sent after the job exists, so the link in it opens a page with
    something on it — a tracking link that arrives before the order
    does is worse than one that arrives a second later.

    Never raises. mNotify being down is not a reason for work to stop
    reaching the floor: the customer can be told late, but a banner
    cannot be printed late because a text message failed.
    """
    if not order.lead_id:
        return

    from apps.storefront.services.messages import payment_text

    try:
        # The app first; an SMS only if no phone of theirs was reached.
        from apps.storefront.services.notify import ready_phrase, tell
        tell(
            order, 'paid', 'Payment received',
            f'{order.order_number}: we’re on it. {ready_phrase(order)}'.strip(),
            sms_text=payment_text(order), text_with=send_sms,
        )
    except Exception:
        logger.error(
            'Could not text %s about %s',
            order.lead.phone, order.order_number, exc_info=True,
        )



def promise_for(order, at=None):
    """
    When this order would be ready at its branch, from the floor as it is.
    The prediction service's own answer: what is queued ahead, the work
    itself, opening hours walked. None where there is no branch, or the
    floor cannot say.
    """
    from apps.jobs.models import Service
    from apps.production.services.prediction_service import PredictionService

    if order.branch_id is None:
        return None

    lines = []
    for line in order.line_items or []:
        service = Service.objects.filter(pk=line.get('service')).first()
        if service is None:
            continue
        specs = line.get('specifications') or {}
        lines.append((service, int(line.get('quantity') or 1), int(specs.get('pages') or 1)))

    try:
        return PredictionService(order.branch).predict(lines, at=at).ready_at
    except Exception:
        logger.exception('Could not work out a promise for %s', order.order_number)
        return None



def _customer_and_link(order):
    """
    The order's customer, and the lead linked to it, so the person's
    online and counter histories are one from the first order on.
    """
    customer = _customer_for(order)
    lead = getattr(order, 'lead', None)
    if customer is not None and lead is not None and lead.customer_id is None:
        lead.customer = customer
        lead.save(update_fields=['customer'])
    return customer
