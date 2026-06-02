# apps/customers/selectors.py
from django.db.models import QuerySet, Q
from django.contrib.postgres.search import TrigramSimilarity

from apps.customers.models import CustomerProfile, CustomerEditLog
from apps.customers.utils import normalise_phone, phone_variants
from apps.finance.models import CreditAccount


def get_customer_list(
    *,
    user,
    customer_type: str = None,
    tier: str = None,
    is_priority: bool = None,
    branch_id: int = None,
    company_name: str = None,
    phone: str = None,
) -> QuerySet:
    qs = CustomerProfile.objects.select_related('preferred_branch').all()

    if customer_type:
        qs = qs.filter(customer_type=customer_type)
    if tier:
        qs = qs.filter(tier=tier)
    if is_priority is not None:
        qs = qs.filter(is_priority=is_priority)
    if branch_id:
        qs = qs.filter(preferred_branch_id=branch_id)
    if company_name:
        qs = qs.filter(company_name__iexact=company_name)
    if phone:
        qs = qs.filter(phone__in=phone_variants(phone))

    return qs


def get_customer_by_id(*, pk: int) -> CustomerProfile:
    return CustomerProfile.objects.select_related('preferred_branch').get(pk=pk)


def get_customer_by_phone(*, phone: str) -> CustomerProfile:
    """
    Looks up a customer by phone, matching all known format variants
    so records stored in any historical format are found correctly.
    Raises CustomerProfile.DoesNotExist if not found.
    """
    variants = phone_variants(phone)
    customer = CustomerProfile.objects.filter(phone__in=variants).first()
    if customer is None:
        raise CustomerProfile.DoesNotExist
    return customer


def search_customers(*, query: str, limit: int = 10) -> QuerySet:
    """
    Unified customer search combining:
    - Exact normalised phone match (highest priority)
    - Trigram similarity on first_name, last_name, company_name

    Returns a ranked queryset — exact phone matches bubble to the top,
    fuzzy name matches follow ordered by similarity score.
    """
    if not query:
        return CustomerProfile.objects.none()

    query = query.strip()

    # Phone path — if query looks like a phone number, do normalised exact match
    digits = ''.join(c for c in query if c.isdigit())
    if len(digits) >= 6:
        variants = phone_variants(query)
        phone_qs = CustomerProfile.objects.filter(
            phone__in=variants
        ).select_related('preferred_branch')
        if phone_qs.exists():
            return phone_qs

    # Name path — trigram similarity across all name fields
    qs = (
        CustomerProfile.objects
        .select_related('preferred_branch')
        .annotate(
            sim_first   = TrigramSimilarity('first_name',   query),
            sim_last    = TrigramSimilarity('last_name',    query),
            sim_company = TrigramSimilarity('company_name', query),
        )
        .filter(
            Q(sim_first__gt=0.1) |
            Q(sim_last__gt=0.1)  |
            Q(sim_company__gt=0.1) |
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query)  |
            Q(company_name__icontains=query)
        )
        .order_by('-sim_first', '-sim_last', '-sim_company')
    )

    return qs[:limit]


def get_customer_edit_log(*, pk: int) -> QuerySet:
    return (
        CustomerEditLog.objects
        .filter(customer_id=pk)
        .select_related('changed_by')
        .order_by('-changed_at')
    )


def get_credit_accounts(*, user, status: str = None) -> QuerySet:
    branch = getattr(user, 'branch', None)
    qs = CreditAccount.objects.select_related(
        'customer', 'branch', 'nominated_by', 'approved_by'
    )
    if branch:
        qs = qs.filter(branch=branch)
    if status:
        qs = qs.filter(status=status)
    return qs


def get_credit_account_by_id(*, pk: int, status: str = None) -> CreditAccount:
    qs = CreditAccount.objects.select_related(
        'customer', 'branch', 'nominated_by', 'approved_by'
    )
    if status:
        qs = qs.filter(status=status)
    return qs.get(pk=pk)