# apps/procurement/services/budget_service.py

import logging
from decimal import Decimal
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

PERIOD_MAP = {
    'ANNUAL'   : ['ANNUAL'],
    'BI_YEARLY': ['H1', 'H2'],
    'QUARTERLY': ['Q1', 'Q2', 'Q3', 'Q4'],
}

CATEGORY_PERIODS = {
    'Q1': ('01-01', '03-31'),
    'Q2': ('04-01', '06-30'),
    'Q3': ('07-01', '09-30'),
    'Q4': ('10-01', '12-31'),
    'H1': ('01-01', '06-30'),
    'H2': ('07-01', '12-31'),
}


class BudgetService:

    @staticmethod
    @transaction.atomic
    def propose(year: int, envelopes: list, proposed_by) -> tuple:
        """
        Finance proposes an annual budget with envelope ceilings.
        envelopes: list of {category, ceiling} dicts.
        Returns (budget, errors).
        """
        from apps.procurement.models import AnnualBudget, BudgetEnvelope

        if AnnualBudget.objects.filter(year=year).exists():
            return None, [f'A budget for {year} already exists.']

        if not envelopes:
            return None, ['At least one budget envelope is required.']

        budget = AnnualBudget.objects.create(
            year        = year,
            status      = AnnualBudget.Status.PENDING_APPROVAL,
            proposed_by = proposed_by,
        )

        for env in envelopes:
            category = env.get('category')
            ceiling  = Decimal(str(env.get('ceiling', 0)))

            if ceiling <= 0:
                continue

            # Create ANNUAL envelope
            BudgetEnvelope.objects.create(
                budget      = budget,
                period_type = BudgetEnvelope.PeriodType.ANNUAL,
                period      = BudgetEnvelope.Period.ANNUAL,
                category    = category,
                ceiling     = ceiling,
            )

            # Create BI_YEARLY envelopes (H1=50%, H2=50%)
            half = (ceiling / 2).quantize(Decimal('0.01'))
            for period in ['H1', 'H2']:
                BudgetEnvelope.objects.create(
                    budget      = budget,
                    period_type = BudgetEnvelope.PeriodType.BI_YEARLY,
                    period      = period,
                    category    = category,
                    ceiling     = half,
                )

            # Create QUARTERLY envelopes (25% each)
            quarter = (ceiling / 4).quantize(Decimal('0.01'))
            for period in ['Q1', 'Q2', 'Q3', 'Q4']:
                BudgetEnvelope.objects.create(
                    budget      = budget,
                    period_type = BudgetEnvelope.PeriodType.QUARTERLY,
                    period      = period,
                    category    = category,
                    ceiling     = quarter,
                )

        logger.info('BudgetService: %s proposed budget for %s', proposed_by.full_name, year)
        return budget, []

    @staticmethod
    @transaction.atomic
    def approve(budget, approved_by) -> tuple:
        """
        Owner approves the annual budget.
        Sets approved_amount = ceiling on all envelopes.
        Returns (budget, errors).
        """
        from apps.procurement.models import AnnualBudget

        if not budget.can_approve:
            return None, [f'Budget cannot be approved � current status is {budget.status}.']

        role = getattr(getattr(approved_by, 'role', None), 'name', '')
        if role != 'SUPER_ADMIN':
            return None, ['Only the Owner can approve the annual budget.']

        from django.db.models import F
        budget.envelopes.update(
            approved_amount=F('ceiling'),
            status='ACTIVE',
        )
        budget.status      = AnnualBudget.Status.APPROVED
        budget.approved_by = approved_by
        budget.approved_at = timezone.now()
        budget.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])

        logger.info('BudgetService: %s approved budget for %s', approved_by.full_name, budget.year)
        return budget, []

    @staticmethod
    def get_active_envelope(year: int, category: str, period: str = None):
        """
        Returns the most granular active envelope for a given category.
        If period is None, derives it from today's date.
        """
        from apps.procurement.models import BudgetEnvelope, AnnualBudget
        import datetime

        if period is None:
            month = timezone.localdate().month
            if month <= 3:
                period = 'Q1'
            elif month <= 6:
                period = 'Q2'
            elif month <= 9:
                period = 'Q3'
            else:
                period = 'Q4'

        try:
            return BudgetEnvelope.objects.get(
                budget__year   = year,
                budget__status = AnnualBudget.Status.APPROVED,
                period         = period,
                category       = category,
                status         = BudgetEnvelope.Status.ACTIVE,
            )
        except BudgetEnvelope.DoesNotExist:
            return None

    @staticmethod
    @transaction.atomic
    def carry_forward_quarter(year: int, from_period: str, to_period: str) -> None:
        """
        Roll unspent balance from one quarter into the next.
        Called at quarter end by a scheduled task.
        """
        from apps.procurement.models import BudgetEnvelope, AnnualBudget
        from django.db.models import F

        source_envelopes = BudgetEnvelope.objects.filter(
            budget__year   = year,
            budget__status = AnnualBudget.Status.APPROVED,
            period         = from_period,
            period_type    = BudgetEnvelope.PeriodType.QUARTERLY,
        )

        for src in source_envelopes:
            unspent = src.available
            if unspent <= 0:
                continue

            try:
                dest = BudgetEnvelope.objects.get(
                    budget   = src.budget,
                    period   = to_period,
                    category = src.category,
                )
                dest.carry_forward += unspent
                dest.save(update_fields=['carry_forward', 'updated_at'])
                logger.info(
                    'BudgetService: carried GHS %s from %s to %s for %s',
                    unspent, from_period, to_period, src.category,
                )
            except BudgetEnvelope.DoesNotExist:
                logger.warning(
                    'BudgetService: no %s envelope found for %s � carry forward skipped',
                    to_period, src.category,
                )

            src.status = BudgetEnvelope.Status.CLOSED
            src.save(update_fields=['status', 'updated_at'])