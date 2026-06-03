from __future__ import annotations

import logging
from decimal import Decimal, ROUND_UP
from django.db import transaction
from django.utils import timezone

from apps.procurement.models import (
    ReplenishmentOrder,
    ReplenishmentLineItem,
    DeliveryDiscrepancy,
    StockReturn,
)

logger = logging.getLogger(__name__)

BUFFER_MULTIPLIER   = Decimal('1.2')
EXCLUDED_CATEGORIES = {'Machinery'}


@transaction.atomic
def prepare_deliverables(branch, actor) -> ReplenishmentOrder:
    from apps.finance.models import WeeklyReport
    active = ReplenishmentOrder.objects.filter(branch=branch).exclude(
        status__in=[ReplenishmentOrder.Status.CLOSED, ReplenishmentOrder.Status.CANCELLED]
    ).first()
    if active:
        raise ValueError(
            f"Branch '{branch.name}' already has an active delivery order "
            f"({active.order_number} — {active.status}). "
            "Complete or cancel it before preparing a new one."
        )
    weekly_report = (
        WeeklyReport.objects
        .filter(branch=branch, status=WeeklyReport.Status.LOCKED)
        .order_by('-year', '-week_number')
        .first()
    )
    if weekly_report is None:
        raise ValueError(
            f"No locked weekly report found for branch '{branch.name}'. "
            "The branch must submit and lock their EOW filing first."
        )
    return generate_order_from_weekly_report(weekly_report, actor)


@transaction.atomic
def generate_order_from_weekly_report(weekly_report, actor) -> ReplenishmentOrder:
    _validate_report_for_generation(weekly_report)
    order_number = _build_order_number(weekly_report)
    order = ReplenishmentOrder.objects.create(
        branch=weekly_report.branch,
        weekly_report=weekly_report,
        order_number=order_number,
        status=ReplenishmentOrder.Status.DRAFT,
    )
    snapshot = weekly_report.inventory_snapshot or {}
    items = snapshot.get('items', [])
    if not items:
        order.delete()
        raise ValueError("Cannot generate replenishment order: no inventory snapshot data on the weekly report.")
    line_items = []
    estimated_total = Decimal('0')
    for item_data in items:
        line = _compute_line_item(order, item_data)
        if line is None:
            continue
        line_items.append(line)
        estimated_total += line.line_total
    if not line_items:
        order.delete()
        raise ValueError("No consumables require replenishment this week. All stock levels are healthy.")
    ReplenishmentLineItem.objects.bulk_create(line_items)
    order.estimated_total = estimated_total.quantize(Decimal('0.01'))
    order.save(update_fields=['estimated_total', 'updated_at'])
    logger.info("generate_order: created %s with %d line items for branch %s",
        order.order_number, len(line_items), weekly_report.branch.name)
    return order


def _compute_line_item(order, item_data):
    from apps.inventory.models import ConsumableItem
    category = item_data.get('category', '')
    if category in EXCLUDED_CATEGORIES:
        return None
    consumable_name = item_data.get('consumable') or item_data.get('name', '')
    if not consumable_name:
        return None
    consumed = Decimal(str(item_data.get('consumed', 0)))
    closing = Decimal(str(item_data.get('closing', 0)))
    reorder_point = Decimal(str(item_data.get('reorder_point', 0)))
    base_name = consumable_name.split('(')[0].strip()
    consumable = ConsumableItem.objects.filter(name__icontains=base_name, is_active=True).first()
    if consumable is None:
        logger.warning("_compute_line_item: '%s' not found — skipping.", consumable_name)
        return None
    if consumable.unit_type == consumable.UnitType.PERCENT:
        if closing >= reorder_point:
            return None
        unit_cost = _get_unit_cost(consumable, order.branch)
        return ReplenishmentLineItem(
            order=order, consumable=consumable, requested_qty=Decimal('1.00'),
            unit_cost=unit_cost, line_total=unit_cost.quantize(Decimal('0.01')),
            notes=f"Toner at {closing}% — below reorder point of {reorder_point}%. Order 1 cartridge.",
        )
    if consumed == 0 and closing >= reorder_point:
        return None
    target_stock = max(consumed * BUFFER_MULTIPLIER, reorder_point)
    raw_replenish = max(Decimal('0'), target_stock - closing)
    if raw_replenish == 0:
        return None
    requested_qty = _round_to_packs(consumable, raw_replenish)
    if requested_qty <= 0:
        return None
    unit_cost = _get_unit_cost(consumable, order.branch)
    line_total = (requested_qty * unit_cost).quantize(Decimal('0.01'))
    notes = _build_line_notes(item_data, raw_replenish, consumable)
    return ReplenishmentLineItem(
        order=order, consumable=consumable, requested_qty=requested_qty,
        unit_cost=unit_cost, line_total=line_total, notes=notes,
    )


def _round_to_packs(consumable, raw_qty):
    try:
        du = consumable.delivery_unit
        if du.is_active and du.pack_size > 0:
            packs = (raw_qty / du.pack_size).to_integral_value(rounding=ROUND_UP)
            return (packs * du.pack_size).quantize(Decimal('0.01'))
    except Exception:
        pass
    return raw_qty.to_integral_value(rounding=ROUND_UP).quantize(Decimal('0.01'))


def _build_line_notes(item_data, raw_replenish, consumable):
    consumed = Decimal(str(item_data.get('consumed', 0)))
    closing = Decimal(str(item_data.get('closing', 0)))
    reorder_point = Decimal(str(item_data.get('reorder_point', 0)))
    try:
        du = consumable.delivery_unit
        packs = (raw_replenish / du.pack_size).to_integral_value(rounding=ROUND_UP)
        pack_info = f" → {int(packs)} {du.pack_label}(s)"
    except Exception:
        pack_info = ''
    return (f"Consumed:{consumed} | Closing:{closing} | "
            f"Reorder point:{reorder_point} | Raw need:{raw_replenish:.2f}{pack_info}")


@transaction.atomic
def submit_to_finance(order, actor):
    _assert_status(order, ReplenishmentOrder.Status.DRAFT, 'submit to Finance')
    order.status = ReplenishmentOrder.Status.PENDING_FINANCE
    order.submitted_to_finance_by = actor
    order.submitted_to_finance_at = timezone.now()
    order.save(update_fields=['status', 'submitted_to_finance_by', 'submitted_to_finance_at', 'updated_at'])
    _notify_finance_team(order)
    return order


@transaction.atomic
def approve_order(order, actor, approved_budget, finance_notes='', line_adjustments=None):
    _assert_status(order, ReplenishmentOrder.Status.PENDING_FINANCE, 'approve')
    if approved_budget <= Decimal('0'):
        raise ValueError("Approved budget must be a positive amount.")
    if line_adjustments:
        _apply_line_adjustments(order, line_adjustments)
    order.status = ReplenishmentOrder.Status.FINANCE_APPROVED
    order.approved_by = actor
    order.approved_at = timezone.now()
    order.approved_budget = approved_budget
    order.finance_notes = finance_notes
    order.save(update_fields=['status', 'approved_by', 'approved_at', 'approved_budget', 'finance_notes', 'updated_at'])

    # Deduct from active STOCK envelope
    try:
        from apps.procurement.services.budget_service import BudgetService
        from django.utils import timezone as tz
        envelope = BudgetService.get_active_envelope(
            year     = tz.localdate().year,
            category = 'STOCK',
        )
        if envelope:
            envelope.deduct(approved_budget)
            logger.info(
                'approve_order: deducted GHS %s from %s %s envelope',
                approved_budget, envelope.period, envelope.category,
            )
        else:
            logger.warning('approve_order: no active STOCK envelope found — deduction skipped')
    except Exception:
        logger.exception('approve_order: budget deduction failed for order %s', order.order_number)

    _notify_operations_approved(order)
    return order


@transaction.atomic
def reject_order(order, actor, finance_notes):
    _assert_status(order, ReplenishmentOrder.Status.PENDING_FINANCE, 'reject')
    if not finance_notes.strip():
        raise ValueError("Rejection reason is required.")
    order.status = ReplenishmentOrder.Status.DRAFT
    order.finance_notes = finance_notes
    order.save(update_fields=['status', 'finance_notes', 'updated_at'])
    _notify_operations_rejected(order)
    return order


@transaction.atomic
def dispatch_order(order, actor, ops_notes=''):
    _assert_status_in(order, {ReplenishmentOrder.Status.CONFIRMED, ReplenishmentOrder.Status.FINANCE_APPROVED}, 'dispatch')
    order.status = ReplenishmentOrder.Status.IN_TRANSIT
    order.dispatched_by = actor
    order.dispatched_at = timezone.now()
    order.ops_notes = ops_notes
    order.save(update_fields=['status', 'dispatched_by', 'dispatched_at', 'ops_notes', 'updated_at'])
    _notify_bm_incoming_delivery(order)
    return order


@transaction.atomic
def record_delivery(order, actor, delivered_quantities):
    _assert_status(order, ReplenishmentOrder.Status.IN_TRANSIT, 'record delivery')
    if not delivered_quantities:
        raise ValueError("At least one delivered quantity must be recorded.")
    line_items = {li.pk: li for li in order.line_items.select_related('consumable')}
    for line_id, qty in delivered_quantities.items():
        line = line_items.get(int(line_id))
        if line is None:
            raise ValueError(f"Line item {line_id} does not belong to order {order.order_number}.")
        qty = Decimal(str(qty))
        if qty < 0:
            raise ValueError(f"Delivered quantity cannot be negative for {line.consumable.name}.")
        line.delivered_qty = qty
        line.save(update_fields=['delivered_qty', 'updated_at'])
    order.status = ReplenishmentOrder.Status.DELIVERED
    order.save(update_fields=['status', 'updated_at'])
    _notify_bm_delivery_arrived(order)
    return order


@transaction.atomic
def accept_delivery(order, actor, accepted_quantities, bm_notes='', returns=None):
    _assert_status(order, ReplenishmentOrder.Status.DELIVERED, 'accept delivery')
    _assert_actor_is_branch_manager(actor, order.branch)
    from apps.inventory.inventory_engine import InventoryEngine
    engine = InventoryEngine(order.branch)
    line_items = {li.pk: li for li in order.line_items.select_related('consumable')}
    for line_id, qty in accepted_quantities.items():
        line = line_items.get(int(line_id))
        if line is None:
            raise ValueError(f"Line item {line_id} does not belong to this order.")
        accepted_qty = Decimal(str(qty))
        if accepted_qty < 0:
            raise ValueError(f"Accepted quantity cannot be negative for {line.consumable.name}.")
        line.accepted_qty = accepted_qty
        line.save(update_fields=['accepted_qty', 'updated_at'])
        if accepted_qty > 0:
            engine.receive_stock(consumable=line.consumable, quantity=accepted_qty, actor=actor,
                notes=f"Received via {order.order_number}")
        if line.has_discrepancy:
            DeliveryDiscrepancy.objects.create(
                order=order, line_item=line, delivered_qty=line.delivered_qty,
                accepted_qty=accepted_qty, difference=line.delivered_qty - accepted_qty,
                bm_reason=bm_notes or 'No reason provided.',
            )
    if returns:
        _process_stock_returns(order, actor, returns)
    order.status = ReplenishmentOrder.Status.CLOSED
    order.accepted_by = actor
    order.accepted_at = timezone.now()
    order.bm_notes = bm_notes
    order.save(update_fields=['status', 'accepted_by', 'accepted_at', 'bm_notes', 'updated_at'])
    _notify_ops_delivery_accepted(order)
    if order.discrepancies.exists():
        _notify_rm_discrepancy(order)
    return order


@transaction.atomic
def cancel_order(order, actor, reason):
    cancellable = {ReplenishmentOrder.Status.DRAFT, ReplenishmentOrder.Status.PENDING_FINANCE,
                   ReplenishmentOrder.Status.FINANCE_APPROVED, ReplenishmentOrder.Status.CONFIRMED}
    if order.status not in cancellable:
        raise ValueError(f"Cannot cancel order in status '{order.status}'.")
    if not reason.strip():
        raise ValueError("Cancellation reason is required.")
    order.status = ReplenishmentOrder.Status.CANCELLED
    order.finance_notes = f"[CANCELLED] {reason}"
    order.save(update_fields=['status', 'finance_notes', 'updated_at'])
    return order


def _validate_report_for_generation(weekly_report):
    from apps.finance.models import WeeklyReport
    if weekly_report.status != WeeklyReport.Status.LOCKED:
        raise ValueError(f"Report is '{weekly_report.status}' — only LOCKED reports can be used.")
    if hasattr(weekly_report, 'replenishment_order'):
        raise ValueError(
            f"A replenishment order already exists for this weekly report "
            f"({weekly_report.replenishment_order.order_number}).")


def _build_order_number(weekly_report):
    return f"REP-{weekly_report.branch.code}-{weekly_report.year}-W{weekly_report.week_number:02d}"


def _get_unit_cost(consumable, branch):
    from apps.inventory.models import BranchStock
    stock = BranchStock.objects.filter(branch=branch, consumable=consumable).first()
    if stock and hasattr(stock, 'unit_cost') and stock.unit_cost:
        return Decimal(str(stock.unit_cost))
    return Decimal('0')


def _apply_line_adjustments(order, adjustments):
    lines = {li.pk: li for li in order.line_items.all()}
    for line_id, approved_qty in adjustments.items():
        line = lines.get(int(line_id))
        if line is None:
            continue
        approved = Decimal(str(approved_qty))
        if approved < 0:
            raise ValueError(f"Approved quantity cannot be negative for line {line_id}.")
        line.approved_qty = approved
        line.line_total = (approved * line.unit_cost).quantize(Decimal('0.01'))
        line.save(update_fields=['approved_qty', 'line_total', 'updated_at'])


def _process_stock_returns(order, actor, returns):
    from apps.inventory.models import ConsumableItem
    for entry in returns:
        consumable = ConsumableItem.objects.filter(pk=entry.get('consumable_id')).first()
        if not consumable:
            continue
        qty = Decimal(str(entry.get('quantity', 0)))
        if qty <= 0:
            continue
        StockReturn.objects.create(
            order=order, consumable=consumable, quantity=qty,
            reason=entry.get('reason', StockReturn.Reason.OTHER),
            reason_notes=entry.get('reason_notes', ''),
            collected_by=actor,
        )


def _assert_status(order, expected, action):
    if order.status != expected:
        raise ValueError(f"Cannot {action}: order '{order.order_number}' is '{order.status}', expected '{expected}'.")


def _assert_status_in(order, allowed, action):
    if order.status not in allowed:
        raise ValueError(f"Cannot {action}: order '{order.order_number}' is '{order.status}'.")


def _assert_actor_is_branch_manager(actor, branch):
    role_name = getattr(getattr(actor, 'role', None), 'name', '')
    if role_name not in ('BRANCH_MANAGER', 'SUPER_ADMIN'):
        raise PermissionError("Only the Branch Manager can accept deliveries.")
    if actor.branch_id and actor.branch_id != branch.pk:
        raise PermissionError("You can only accept deliveries for your own branch.")


def _notify_finance_team(order):
    try:
        from apps.notifications.models import Notification
        from apps.accounts.models import CustomUser
        users = CustomUser.objects.filter(role__name='FINANCE', is_active=True)
        Notification.objects.bulk_create([
            Notification(recipient=u,
                message=f"Replenishment order {order.order_number} for {order.branch.name} needs approval.") for u in users])
    except Exception:
        logger.exception("_notify_finance_team failed")


def _notify_operations_approved(order):
    _notify_user_if_exists(order.submitted_to_finance_by,
        f"Order {order.order_number} approved. Budget: GHS {order.approved_budget}. Ready to dispatch.")


def _notify_operations_rejected(order):
    _notify_user_if_exists(order.submitted_to_finance_by,
        f"Order {order.order_number} returned by Finance: {order.finance_notes}")


def _notify_bm_incoming_delivery(order):
    try:
        from apps.accounts.models import CustomUser
        bm = CustomUser.objects.filter(
            branch=order.branch, role__name='BRANCH_MANAGER', is_active=True).first()
        _notify_user_if_exists(bm, f"Delivery {order.order_number} is on its way to your branch.")
    except Exception:
        logger.exception("_notify_bm_incoming_delivery failed")


def _notify_bm_delivery_arrived(order):
    try:
        from apps.accounts.models import CustomUser
        bm = CustomUser.objects.filter(
            branch=order.branch, role__name='BRANCH_MANAGER', is_active=True).first()
        _notify_user_if_exists(bm,
            f"Delivery {order.order_number} has arrived. Please accept on your dashboard.")
    except Exception:
        logger.exception("_notify_bm_delivery_arrived failed")


def _notify_ops_delivery_accepted(order):
    _notify_user_if_exists(order.dispatched_by,
        f"Order {order.order_number} accepted by {order.branch.name}. Cycle closed.")


def _notify_rm_discrepancy(order):
    try:
        from apps.notifications.models import Notification
        from apps.accounts.models import CustomUser
        rms = CustomUser.objects.filter(
            role__name='REGIONAL_MANAGER', region=order.branch.region, is_active=True)
        Notification.objects.bulk_create([
            Notification(recipient=rm,
                message=f"Discrepancy on {order.order_number} for {order.branch.name}. Review required.") for rm in rms])
    except Exception:
        logger.exception("_notify_rm_discrepancy failed")


def _notify_user_if_exists(user, message):
    if user is None:
        return
    try:
        from apps.notifications.models import Notification
        Notification.objects.create(recipient=user, message=message)
    except Exception:
        logger.exception("_notify_user_if_exists failed")