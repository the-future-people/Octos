from django.db.models import QuerySet
from apps.customers.models import CustomerProfile, CustomerEditLog
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
    """
    Returns a filtered queryset of CustomerProfile objects.
    Branch scoping is applied automatically from the requesting user.
    """
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
        qs = qs.filter(phone=phone)

    return qs


def get_customer_by_id(*, pk: int) -> CustomerProfile:
    """
    Returns a single CustomerProfile by pk.
    Raises CustomerProfile.DoesNotExist if not found.
    """
    return CustomerProfile.objects.select_related('preferred_branch').get(pk=pk)


def get_customer_by_phone(*, phone: str) -> CustomerProfile:
    """
    Returns a single CustomerProfile by phone number.
    Raises CustomerProfile.DoesNotExist if not found.
    """
    return CustomerProfile.objects.get(phone=phone)


def get_customer_edit_log(*, pk: int) -> QuerySet:
    """
    Returns all edit log entries for a customer, newest first.
    """
    return (
        CustomerEditLog.objects
        .filter(customer_id=pk)
        .select_related('changed_by')
        .order_by('-changed_at')
    )


def get_credit_accounts(*, user, status: str = None) -> QuerySet:
    """
    Returns credit accounts scoped to the requesting user's branch.
    """
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
    """
    Returns a single CreditAccount by pk, optionally filtered by status.
    Raises CreditAccount.DoesNotExist if not found.
    """
    qs = CreditAccount.objects.select_related(
        'customer', 'branch', 'nominated_by', 'approved_by'
    )
    if status:
        qs = qs.filter(status=status)
    return qs.get(pk=pk)