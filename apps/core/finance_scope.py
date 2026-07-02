# apps/core/finance_scope.py
"""
Finance scope resolution.

Every Finance API view calls get_finance_scope(user) to get the
correct queryset filters for branches visible to that user.

Technical note: This pattern is called a "query scope" or "row-level
security" helper. Instead of duplicating filter logic in every view,
we centralise it here. Views stay thin and consistent.
"""

from django.db.models import Q


NATIONAL_ROLES = {
    'NATIONAL_FINANCE_HEAD',
    'NATIONAL_FINANCE_DEPUTY',
    'SUPER_ADMIN',
    'FINANCE',
}

BELT_ROLES = {
    'BELT_FINANCE_OFFICER',
    'BELT_FINANCE_DEPUTY',
}

REGIONAL_ROLES = {
    'REGIONAL_FINANCE_OFFICER',
    'REGIONAL_FINANCE_DEPUTY',
}


def get_role_name(user) -> str:
    return getattr(getattr(user, 'role', None), 'name', '') or ''


def get_finance_scope(user) -> dict:
    role = get_role_name(user)

    if role in NATIONAL_ROLES:
        return {
            'scope_label'  : 'National',
            'branch_filter': Q(),
            'region_filter': Q(),
            'is_national'  : True,
            'is_belt'      : False,
            'is_regional'  : False,
        }

    if role in BELT_ROLES:
        belt = getattr(user, 'belt', None)
        if not belt:
            return _empty_scope('Belt (unassigned)')
        return {
            'scope_label'  : belt.name,
            'branch_filter': Q(branch__region__belt=belt),
            'region_filter': Q(belt=belt),
            'is_national'  : False,
            'is_belt'      : True,
            'is_regional'  : False,
        }

    if role in REGIONAL_ROLES:
        region = getattr(user, 'region', None)
        if not region:
            return _empty_scope('Region (unassigned)')
        return {
            'scope_label'  : region.name,
            'branch_filter': Q(branch__region=region),
            'region_filter': Q(pk=region.pk),
            'is_national'  : False,
            'is_belt'      : False,
            'is_regional'  : True,
        }

    return _empty_scope('Unknown')


def _empty_scope(label: str) -> dict:
    return {
        'scope_label'  : label,
        'branch_filter': Q(pk__in=[]),
        'region_filter': Q(pk__in=[]),
        'is_national'  : False,
        'is_belt'      : False,
        'is_regional'  : False,
    }


def is_finance_user(user) -> bool:
    role = get_role_name(user)
    return role in (NATIONAL_ROLES | BELT_ROLES | REGIONAL_ROLES)


def get_scope_label(user) -> str:
    return get_finance_scope(user)['scope_label']


# ── Operational scope (Branch Manager / Regional Manager / Belt Manager) ──────
# Distinct from the Finance-department scope above. This covers the
# operational management hierarchy — used for things like credit
# accounts, job transitions, and pricing, which BMs and RMs manage
# directly, not the Finance department.

OPERATIONAL_NATIONAL_ROLES = {
    'SUPER_ADMIN',
}

OPERATIONAL_BELT_ROLES = {
    'BELT_MANAGER',
}

OPERATIONAL_REGIONAL_ROLES = {
    'REGIONAL_MANAGER',
}

OPERATIONAL_BRANCH_ROLES = {
    'BRANCH_MANAGER',
    'CASHIER',
    'ATTENDANT',
}


def get_branch_scope(user) -> dict:
    """
    Returns a dict with a 'branch_filter' Q object usable directly in
    querysets, e.g. CreditAccount.objects.filter(scope['branch_filter']).

    Fails closed — an unassigned or unrecognised role sees nothing,
    never everything.
    """
    role = get_role_name(user)

    if role in OPERATIONAL_NATIONAL_ROLES:
        return {'scope_label': 'National', 'branch_filter': Q()}

    if role in OPERATIONAL_BELT_ROLES:
        belt = getattr(user, 'belt', None)
        if not belt:
            return {'scope_label': 'Belt (unassigned)', 'branch_filter': Q(pk__in=[])}
        return {'scope_label': belt.name, 'branch_filter': Q(region__belt=belt)}

    if role in OPERATIONAL_REGIONAL_ROLES:
        region = getattr(user, 'region', None)
        if not region:
            return {'scope_label': 'Region (unassigned)', 'branch_filter': Q(pk__in=[])}
        return {'scope_label': region.name, 'branch_filter': Q(region=region)}

    if role in OPERATIONAL_BRANCH_ROLES:
        branch = getattr(user, 'branch', None)
        if not branch:
            return {'scope_label': 'Branch (unassigned)', 'branch_filter': Q(pk__in=[])}
        return {'scope_label': branch.name, 'branch_filter': Q(pk=branch.pk)}

    return {'scope_label': 'Unknown', 'branch_filter': Q(pk__in=[])}