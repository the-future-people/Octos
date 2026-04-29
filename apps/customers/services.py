from django.utils import timezone
from django.db import transaction

from apps.customers.models import CustomerProfile, CustomerEditLog
from apps.finance.models import CreditAccount


# ── Customer creation ─────────────────────────────────────────────────────────

class CustomerAlreadyExists(Exception):
    pass


class EmployeePhoneConflict(Exception):
    pass


def create_customer(*, user, data: dict) -> CustomerProfile:
    """
    Creates a new CustomerProfile.
    - Assigns branch from the creating user if not supplied.
    - Raises CustomerAlreadyExists if phone is already registered.
    - Raises EmployeePhoneConflict if phone belongs to a branch employee.
    """
    phone = data.get('phone', '').strip()

    # Duplicate phone check
    if phone and CustomerProfile.objects.filter(phone=phone).exists():
        raise CustomerAlreadyExists(
            f'A customer with phone {phone} already exists.'
        )

    # Employee phone conflict check
    if phone:
        from apps.accounts.models import CustomUser
        if CustomUser.objects.filter(phone=phone).exists():
            raise EmployeePhoneConflict(
                f'Phone {phone} belongs to a branch employee.'
            )

    branch = data.pop('preferred_branch', None) or getattr(user, 'branch', None)

    customer = CustomerProfile.objects.create(
        preferred_branch=branch,
        **data,
    )
    return customer


# ── Customer editing ──────────────────────────────────────────────────────────

class FieldNotEditable(Exception):
    pass


EDITABLE_FIELDS = {
    'INDIVIDUAL': [
        'title', 'title_other', 'first_name', 'last_name',
        'gender', 'date_of_birth', 'phone', 'secondary_phone',
        'email', 'preferred_contact', 'address',
    ],
    'BUSINESS': [
        'title', 'title_other', 'first_name', 'last_name',
        'gender', 'date_of_birth', 'phone', 'secondary_phone',
        'email', 'preferred_contact', 'address', 'company_name',
    ],
    'INSTITUTION': [
        'title', 'title_other', 'first_name', 'last_name',
        'gender', 'date_of_birth', 'phone', 'secondary_phone',
        'email', 'preferred_contact', 'address',
        'company_name', 'institution_subtype',
    ],
}


def edit_customer(*, pk: int, user, data: dict) -> CustomerProfile:
    """
    Applies allowed field edits to a CustomerProfile.
    Writes an audit log entry for every changed field.
    Raises FieldNotEditable for disallowed fields.
    Raises CustomerAlreadyExists for duplicate phone.
    Returns the updated CustomerProfile.
    """
    customer = CustomerProfile.objects.get(pk=pk)
    allowed  = EDITABLE_FIELDS.get(customer.customer_type, [])
    errors   = {}
    changes  = []

    for field, new_value in data.items():
        if field not in allowed:
            errors[field] = f'Field "{field}" is not editable.'
            continue

        old_value = str(getattr(customer, field, '') or '')
        new_value = str(new_value or '').strip()

        if old_value == new_value:
            continue

        if field == 'phone':
            if CustomerProfile.objects.filter(phone=new_value).exclude(pk=pk).exists():
                errors['phone'] = 'A customer with this phone number already exists.'
                continue

        setattr(customer, field, new_value)
        changes.append(CustomerEditLog(
            customer   = customer,
            changed_by = user,
            field_name = field,
            old_value  = old_value,
            new_value  = new_value,
        ))

    if errors:
        from rest_framework.exceptions import ValidationError
        raise ValidationError(errors)

    if changes:
        with transaction.atomic():
            customer.save()
            CustomerEditLog.objects.bulk_create(changes)

    return customer


# ── Credit nomination ─────────────────────────────────────────────────────────

def nominate_credit(
    *,
    customer_pk: int,
    user,
    credit_limit,
    payment_terms: int,
    account_type: str,
    contact_person: str = '',
) -> CreditAccount:
    """
    Nominates a customer for a credit account.
    Creates the account in PENDING status.
    Notifies the Belt Manager via the notifications service.
    """
    customer = CustomerProfile.objects.get(pk=customer_pk)

    account = CreditAccount.objects.create(
        customer      = customer,
        branch        = getattr(user, 'branch', None),
        nominated_by  = user,
        nominated_at  = timezone.now(),
        status        = CreditAccount.Status.PENDING,
        credit_limit  = credit_limit,
        payment_terms = payment_terms,
        account_type  = account_type,
        contact_person= contact_person,
    )

    # Notify Belt Manager
    try:
        from apps.notifications.services import notify
        from apps.accounts.models import CustomUser
        belt_managers = CustomUser.objects.filter(
            role__name='BELT_MANAGER',
            branch__belt=user.branch.belt if user.branch else None,
        )
        for bm in belt_managers:
            notify(
                recipient=bm,
                message=(
                    f"{user.full_name} has nominated "
                    f"{customer.display_name} for a credit account "
                    f"(limit: GHS {credit_limit}). Please review."
                ),
                category='CREDIT',
                link=f'/credit/{account.id}/',
            )
    except Exception:
        pass  # Notifications are non-critical

    return account