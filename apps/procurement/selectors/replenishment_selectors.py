"""
Replenishment Selectors
=======================
All read-only query logic lives here.
Views and services import from selectors — never write raw ORM queries in views.
"""
from __future__ import annotations

from django.db.models import QuerySet, Prefetch
from apps.procurement.models import (
    ReplenishmentOrder,
    ReplenishmentLineItem,
    DeliveryDiscrepancy,
    StockReturn,
)


# ── Order selectors ───────────────────────────────────────────────────────────

def get_order_by_id(order_id: int) -> ReplenishmentOrder:
    """
    Fetch a single order with all related data pre-loaded.
    Raises ReplenishmentOrder.DoesNotExist if not found.
    """
    return (
        ReplenishmentOrder.objects
        .select_related(
            'branch',
            'branch__region',
            'weekly_report',
            'submitted_to_finance_by',
            'approved_by',
            'dispatched_by',
            'accepted_by',
        )
        .prefetch_related(
            Prefetch(
                'line_items',
                queryset=ReplenishmentLineItem.objects.select_related(
                    'consumable',
                    'consumable__category',
                ).order_by('consumable__category__name', 'consumable__name'),
            ),
            Prefetch(
                'discrepancies',
                queryset=DeliveryDiscrepancy.objects.select_related('line_item__consumable'),
            ),
            'stock_returns__consumable',
        )
        .get(pk=order_id)
    )


def get_orders_for_branch(branch) -> QuerySet:
    """All orders for a branch, newest first."""
    return (
        ReplenishmentOrder.objects
        .filter(branch=branch)
        .select_related('branch', 'weekly_report', 'approved_by')
        .prefetch_related('line_items__consumable')
        .order_by('-created_at')
    )


def get_orders_for_operations_manager() -> QuerySet:
    """
    All orders visible to Operations Manager:
    everything except CANCELLED, ordered by urgency.
    """
    return (
        ReplenishmentOrder.objects
        .exclude(status=ReplenishmentOrder.Status.CANCELLED)
        .select_related(
            'branch',
            'branch__region',
            'weekly_report',
            'submitted_to_finance_by',
            'approved_by',
        )
        .prefetch_related('line_items__consumable')
        .order_by(
            # Priority order: IN_TRANSIT first, then FINANCE_APPROVED, etc.
            _status_priority_expression(),
            '-created_at',
        )
    )


def get_orders_pending_finance_approval() -> QuerySet:
    """Orders awaiting Finance sign-off."""
    return (
        ReplenishmentOrder.objects
        .filter(status=ReplenishmentOrder.Status.PENDING_FINANCE)
        .select_related('branch', 'weekly_report', 'submitted_to_finance_by')
        .prefetch_related(
            Prefetch(
                'line_items',
                queryset=ReplenishmentLineItem.objects.select_related(
                    'consumable', 'consumable__category'
                ),
            )
        )
        .order_by('submitted_to_finance_at')
    )


def get_pending_delivery_for_branch(branch) -> ReplenishmentOrder | None:
    """
    Returns the single DELIVERED order awaiting BM acceptance at a branch.
    There should never be more than one simultaneously.
    """
    return (
        ReplenishmentOrder.objects
        .filter(branch=branch, status=ReplenishmentOrder.Status.DELIVERED)
        .select_related('branch', 'dispatched_by')
        .prefetch_related(
            Prefetch(
                'line_items',
                queryset=ReplenishmentLineItem.objects.select_related(
                    'consumable', 'consumable__category'
                ),
            )
        )
        .first()
    )


def get_orders_for_rm(region) -> QuerySet:
    """All orders across branches in a region, for RM oversight."""
    return (
        ReplenishmentOrder.objects
        .filter(branch__region=region)
        .exclude(status=ReplenishmentOrder.Status.CANCELLED)
        .select_related('branch', 'approved_by', 'dispatched_by')
        .prefetch_related('discrepancies', 'line_items__consumable')
        .order_by('-created_at')
    )


def get_all_orders(filters: dict | None = None) -> QuerySet:
    """
    Full order list for Super Admin / Finance overview.
    filters: optional dict with keys: status, branch_id, week_number, year
    """
    qs = (
        ReplenishmentOrder.objects
        .select_related('branch', 'branch__region', 'approved_by')
        .prefetch_related('line_items')
        .order_by('-created_at')
    )
    if filters:
        if filters.get('status'):
            qs = qs.filter(status=filters['status'])
        if filters.get('branch_id'):
            qs = qs.filter(branch_id=filters['branch_id'])
        if filters.get('week_number'):
            qs = qs.filter(weekly_report__week_number=filters['week_number'])
        if filters.get('year'):
            qs = qs.filter(weekly_report__year=filters['year'])
    return qs


# ── Discrepancy selectors ─────────────────────────────────────────────────────

def get_pending_discrepancies(region=None) -> QuerySet:
    """Unresolved discrepancies, optionally scoped to a region."""
    qs = (
        DeliveryDiscrepancy.objects
        .filter(resolution=DeliveryDiscrepancy.Resolution.PENDING)
        .select_related(
            'order',
            'order__branch',
            'line_item__consumable',
            'resolved_by',
        )
        .order_by('-created_at')
    )
    if region:
        qs = qs.filter(order__branch__region=region)
    return qs


def get_discrepancies_for_order(order: ReplenishmentOrder) -> QuerySet:
    return (
        DeliveryDiscrepancy.objects
        .filter(order=order)
        .select_related('line_item__consumable', 'resolved_by')
        .order_by('-created_at')
    )


# ── Stock return selectors ────────────────────────────────────────────────────

def get_returns_for_order(order: ReplenishmentOrder) -> QuerySet:
    return (
        StockReturn.objects
        .filter(order=order)
        .select_related('consumable', 'collected_by', 'confirmed_by_bm')
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _status_priority_expression():
    """
    Returns a Case expression for ordering orders by operational urgency.
    IN_TRANSIT first, then DELIVERED, FINANCE_APPROVED, PENDING_FINANCE, DRAFT.
    """
    from django.db.models import Case, When, IntegerField

    return Case(
        When(status=ReplenishmentOrder.Status.IN_TRANSIT,       then=1),
        When(status=ReplenishmentOrder.Status.DELIVERED,         then=2),
        When(status=ReplenishmentOrder.Status.FINANCE_APPROVED,  then=3),
        When(status=ReplenishmentOrder.Status.PENDING_FINANCE,   then=4),
        When(status=ReplenishmentOrder.Status.DRAFT,             then=5),
        default=6,
        output_field=IntegerField(),
    )


# ── Branch health selectors ───────────────────────────────────────────────────

def get_all_branches_with_delivery_status():
    """
    Returns all active branches with their latest locked weekly report
    and any active replenishment order. Used for the ops portal branches tab.
    """
    from apps.organization.models import Branch
    from apps.finance.models import WeeklyReport
    from django.db.models import Subquery, OuterRef

    branches = (
        Branch.objects
        .filter(is_active=True)
        .select_related('region')
        .order_by('name')
    )

    result = []
    for branch in branches:
        # Latest locked EOW
        latest_report = (
            WeeklyReport.objects
            .filter(branch=branch, status=WeeklyReport.Status.LOCKED)
            .order_by('-year', '-week_number')
            .first()
        )

        # Active order (not closed/cancelled)
        active_order = (
            ReplenishmentOrder.objects
            .filter(branch=branch)
            .exclude(status__in=[
                ReplenishmentOrder.Status.CLOSED,
                ReplenishmentOrder.Status.CANCELLED,
            ])
            .select_related('weekly_report')
            .first()
        )

        # Low stock items from snapshot
        low_stock_items = []
        if latest_report and latest_report.inventory_snapshot:
            items = latest_report.inventory_snapshot.get('items', [])
            low_stock_items = [
                i['consumable'] for i in items
                if i.get('is_low') and i.get('category') != 'Machinery'
            ]

        result.append({
            'branch':          branch,
            'latest_report':   latest_report,
            'active_order':    active_order,
            'low_stock_items': low_stock_items,
            'low_stock_count': len(low_stock_items),
            'can_prepare':     latest_report is not None and active_order is None,
        })

    return result


def get_active_order_for_branch(branch) -> ReplenishmentOrder | None:
    """Returns the current active (non-closed, non-cancelled) order for a branch."""
    return (
        ReplenishmentOrder.objects
        .filter(branch=branch)
        .exclude(status__in=[
            ReplenishmentOrder.Status.CLOSED,
            ReplenishmentOrder.Status.CANCELLED,
        ])
        .select_related('branch', 'weekly_report')
        .prefetch_related(
            Prefetch(
                'line_items',
                queryset=ReplenishmentLineItem.objects.select_related(
                    'consumable',
                    'consumable__category',
                    'consumable__delivery_unit',
                ).order_by('consumable__category__name', 'consumable__name'),
            )
        )
        .first()
    )