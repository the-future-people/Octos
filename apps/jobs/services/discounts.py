"""
Lowering a price on a proforma or a job (17 Nov 2026).

Who: the Branch Manager and the owner. Attendants and cashiers see prices,
they don't change them.

How low: the owner, as low as he likes. The Branch Manager, as long as the
work still earns CostSettings.floor_multiple times its cost (2.5: about
GHS 1.90 for a typical colour page). Lower than that, or when part of the
work has no cost set and the cut is more than unknown_cost_limit percent,
it goes to the owner, who approves or declines (notified, like profile
changes). Every cut has a reason and a name, and the latest one replaces
any before it.

What changes: the proforma's or job's own total, so the cashier's amount
due, balances and receipts are right without knowing discounts exist;
discount_amount, discount_reason and discount_by say how much, why and who.
Only before any money is taken: a job awaiting its first payment, or a
proforma not yet converted or expired.
"""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

CENT = Decimal('0.01')
MANAGERS = ('BRANCH_MANAGER',)


class DiscountRefused(Exception):
    """Said to the person, as is."""


def is_owner(user):
    role = getattr(getattr(user, 'role', None), 'name', '')
    return bool(getattr(user, 'is_business_owner', False)) or role == 'SUPER_ADMIN'


def may_discount(user):
    return is_owner(user) or getattr(getattr(user, 'role', None), 'name', '') in MANAGERS


# ── The thing being discounted ────────────────────────────────────────────

def _target(job=None, proforma=None):
    from apps.jobs.models import Job, ProformaInvoice
    if job is not None:
        return job if isinstance(job, Job) else Job.objects.get(pk=job)
    return proforma if isinstance(proforma, ProformaInvoice) else ProformaInvoice.objects.get(pk=proforma)


def _is_job(target):
    from apps.jobs.models import Job
    return isinstance(target, Job)


def _total(target):
    return Decimal(str((target.estimated_cost if _is_job(target) else target.total) or 0))


def _changeable(target):
    from apps.jobs.models import Job, ProformaInvoice
    if _is_job(target):
        if target.status != Job.PENDING_PAYMENT or (target.amount_paid or 0) > 0:
            return "This job's price can't change now: payment has started."
        return ''
    if target.status not in (ProformaInvoice.Status.DRAFT, ProformaInvoice.Status.ISSUED):
        return "This proforma's price can't change now."
    return ''


def summary(target):
    """Everything the discount panel shows, for a job or a proforma."""
    from apps.jobs.models import CostSettings, PriceCut
    from apps.jobs.services.costing import job_cost, proforma_cost

    s = CostSettings.current()
    total = _total(target)
    before = (total + target.discount_amount).quantize(CENT)          # after any bulk price
    listed = (before + target.bulk_saving).quantize(CENT)
    cost = job_cost(target) if _is_job(target) else proforma_cost(target)
    floor = (cost['cost'] * s.floor_multiple).quantize(CENT) if cost['known'] else None
    filter_ = {'job': target} if _is_job(target) else {'proforma': target}
    pending = PriceCut.objects.filter(status=PriceCut.Status.PENDING, **filter_).select_related('asked_by').first()
    return {
        'kind': 'job' if _is_job(target) else 'proforma',
        'id': target.pk,
        'list_total': str(listed),
        'bulk_saving': str(target.bulk_saving),
        'before_total': str(before),
        'discount_amount': str(target.discount_amount),
        'discount_reason': target.discount_reason,
        'discount_by': target.discount_by.full_name if target.discount_by_id else '',
        'total': str(total),
        'saved': str((listed - total).quantize(CENT)),
        'cost': str(cost['cost']),
        'cost_known': cost['known'],
        'floor_total': str(floor) if floor is not None else None,
        'floor_multiple': str(s.floor_multiple),
        'unknown_cost_limit': str(s.unknown_cost_limit),
        'page_units': cost['page_units'],
        'page_total': str(cost['page_total']),
        'changeable': not _changeable(target),
        'why_not': _changeable(target),
        'pending': _cut_row(pending) if pending else None,
    }


# ── Lowering a price ──────────────────────────────────────────────────────

def lower(user, new_total, reason, job=None, proforma=None):
    """
    Lower (or restore) the price. Returns the PriceCut: APPLIED, or PENDING
    when the owner must decide. Raises DiscountRefused with the reason.
    """
    from apps.jobs.models import CostSettings, PriceCut
    from apps.jobs.services.costing import job_cost, proforma_cost

    if not may_discount(user):
        raise DiscountRefused('Only the Branch Manager or the owner can lower a price.')
    target = _target(job, proforma)
    blocked = _changeable(target)
    if blocked:
        raise DiscountRefused(blocked)
    reason = (reason or '').strip()
    if not reason:
        raise DiscountRefused('Say why the price is lower: it goes on the record.')
    try:
        new_total = Decimal(str(new_total)).quantize(CENT)
    except Exception:
        raise DiscountRefused('Give the new price as a number.')
    before = (_total(target) + target.discount_amount).quantize(CENT)
    if new_total <= 0:
        raise DiscountRefused('The new price must be more than zero.')
    if new_total > before:
        raise DiscountRefused(f'That is more than the price, GHS {before:,.2f}.')

    s = CostSettings.current()
    cost = job_cost(target) if _is_job(target) else proforma_cost(target)
    floor = (cost['cost'] * s.floor_multiple).quantize(CENT) if cost['known'] else None
    amount = before - new_total
    if is_owner(user):
        allowed = True
    elif floor is not None:
        allowed = new_total >= floor
    else:
        allowed = before > 0 and amount / before * 100 <= s.unknown_cost_limit

    filter_ = {'job': target} if _is_job(target) else {'proforma': target}
    with transaction.atomic():
        PriceCut.objects.filter(status=PriceCut.Status.PENDING, **filter_).update(status=PriceCut.Status.REPLACED)
        cut = PriceCut.objects.create(
            **filter_, before_total=before, new_total=new_total, amount=amount, reason=reason[:300],
            cost=cost['cost'] if cost['known'] else None, floor_total=floor,
            status=PriceCut.Status.APPLIED if allowed else PriceCut.Status.PENDING, asked_by=user,
        )
        if allowed:
            _apply(target, cut)
    if not allowed:
        _ask_owner(cut, target)
    return cut


def approve(owner, cut_id):
    from apps.jobs.models import PriceCut
    cut = _decidable(owner, cut_id)
    target = cut.job or cut.proforma
    blocked = _changeable(target)
    if blocked:
        raise DiscountRefused(blocked)
    with transaction.atomic():
        cut.status, cut.decided_by, cut.decided_at = PriceCut.Status.APPLIED, owner, timezone.now()
        cut.save(update_fields=['status', 'decided_by', 'decided_at', 'updated_at'])
        _apply(target, cut)
    _tell(cut.asked_by, owner, f'{owner.full_name} approved GHS {cut.new_total:,.2f} for {_label(target)}.', target)
    return cut


def decline(owner, cut_id, note=''):
    from apps.jobs.models import PriceCut
    cut = _decidable(owner, cut_id)
    cut.status, cut.decided_by, cut.decided_at = PriceCut.Status.DECLINED, owner, timezone.now()
    cut.note = (note or '')[:300]
    cut.save(update_fields=['status', 'decided_by', 'decided_at', 'note', 'updated_at'])
    target = cut.job or cut.proforma
    said = f': {cut.note}' if cut.note else '.'
    _tell(cut.asked_by, owner, f"{owner.full_name} didn't approve GHS {cut.new_total:,.2f} for {_label(target)}{said}",
          target)
    return cut


def waiting():
    """Price cuts waiting for the owner, oldest first."""
    from apps.jobs.models import PriceCut
    cuts = (PriceCut.objects.filter(status=PriceCut.Status.PENDING)
            .select_related('asked_by', 'job', 'proforma', 'job__customer', 'proforma__customer')
            .order_by('created_at'))
    return [_cut_row(c) for c in cuts]


# ── Inside ────────────────────────────────────────────────────────────────

def _apply(target, cut):
    """The total takes the cut; the amount, reason and name go beside it."""
    target.discount_amount = cut.amount
    target.discount_reason = cut.reason if cut.amount else ''
    target.discount_by = cut.asked_by if cut.amount else None
    if _is_job(target):
        target.estimated_cost = cut.new_total
        target.save(update_fields=['estimated_cost', 'discount_amount', 'discount_reason', 'discount_by', 'updated_at'])
    else:
        target.total = cut.new_total
        target.save(update_fields=['total', 'discount_amount', 'discount_reason', 'discount_by', 'updated_at'])


def _decidable(owner, cut_id):
    from apps.jobs.models import PriceCut
    if not is_owner(owner):
        raise DiscountRefused('Only the owner decides on prices below the floor.')
    cut = PriceCut.objects.select_related('job', 'proforma', 'asked_by').filter(pk=cut_id).first()
    if cut is None or cut.status != PriceCut.Status.PENDING:
        raise DiscountRefused('That request has already been decided.')
    return cut


def _label(target):
    return target.job_number if _is_job(target) else target.proforma_number


def _link(target):
    return f'/bm/jobs/?open={target.pk}' if _is_job(target) else f'/bm/proformas/?open={target.pk}'


def _who(target):
    customer = getattr(target, 'customer', None)
    return (customer.full_name if customer else '') or getattr(target, 'title', '') or ''


def _cut_row(cut):
    target = cut.job or cut.proforma
    return {
        'id': cut.pk,
        'kind': 'job' if cut.job_id else 'proforma',
        'target_id': target.pk,
        'number': _label(target),
        'customer': _who(target),
        'before_total': str(cut.before_total),
        'new_total': str(cut.new_total),
        'amount': str(cut.amount),
        'percent': str(cut.percent),
        'cost': str(cut.cost) if cut.cost is not None else None,
        'floor_total': str(cut.floor_total) if cut.floor_total is not None else None,
        'reason': cut.reason,
        'asked_by': cut.asked_by.full_name,
        'asked_at': cut.created_at.isoformat(),
        'status': cut.status,
    }


def _ask_owner(cut, target):
    from apps.accounts.models import CustomUser
    below = (f'below the floor of GHS {cut.floor_total:,.2f}' if cut.floor_total is not None
             else 'more than the limit for work with no cost set')
    message = (f'{cut.asked_by.full_name} asks to lower {_label(target)} ({_who(target) or "a customer"}) '
               f'from GHS {cut.before_total:,.2f} to GHS {cut.new_total:,.2f}, {below}. Reason: {cut.reason}')
    for owner in CustomUser.objects.filter(is_business_owner=True, is_active=True):
        _tell(owner, cut.asked_by, message, target, link='/eye')


def _tell(recipient, actor, message, target, link=None):
    from apps.notifications.services import notify
    try:
        notify(recipient=recipient, verb='system', actor=actor, message=message, link=link or _link(target))
    except Exception:
        pass
