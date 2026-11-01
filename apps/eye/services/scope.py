"""
Where the Eye is looking: the whole company, a belt, a region or a branch.

A scope is written as a key: 'company', 'belt:3', 'region:7', 'branch:12'.
Every figure the Eye shows is computed for the branches a scope covers,
so a branch, its region, its belt and the company can never disagree:
the higher levels are only ever sums of the lower ones.

A branch with no region (headquarters) sits directly under the company.
"""

from dataclasses import dataclass
from typing import Optional


class ScopeNotFound(Exception):
    pass


@dataclass(frozen=True)
class Scope:
    kind: str                 # company | belt | region | branch
    id: Optional[int]
    name: str
    branch_ids: tuple

    @property
    def key(self) -> str:
        return 'company' if self.kind == 'company' else f'{self.kind}:{self.id}'

    def as_dict(self) -> dict:
        return {'key': self.key, 'kind': self.kind, 'id': self.id, 'name': self.name}


COMPANY_NAME = 'Farhat (Ghana)'


def _branches():
    from apps.organization.models import Branch
    return Branch.objects.filter(is_active=True)


def resolve(key: Optional[str]) -> Scope:
    from apps.organization.models import Belt, Region, Branch

    key = (key or 'company').strip()
    if key == 'company':
        ids = tuple(_branches().values_list('id', flat=True))
        return Scope('company', None, COMPANY_NAME, ids)

    kind, _, raw = key.partition(':')
    if not raw.isdigit():
        raise ScopeNotFound(key)
    pk = int(raw)

    if kind == 'belt':
        obj = Belt.objects.filter(pk=pk).first()
        if not obj:
            raise ScopeNotFound(key)
        ids = tuple(_branches().filter(region__belt=obj).values_list('id', flat=True))
        return Scope('belt', pk, obj.name, ids)

    if kind == 'region':
        obj = Region.objects.filter(pk=pk).first()
        if not obj:
            raise ScopeNotFound(key)
        ids = tuple(_branches().filter(region=obj).values_list('id', flat=True))
        return Scope('region', pk, obj.name, ids)

    if kind == 'branch':
        obj = Branch.objects.filter(pk=pk).first()
        if not obj:
            raise ScopeNotFound(key)
        return Scope('branch', pk, obj.name, (pk,))

    raise ScopeNotFound(key)


def children(scope: Scope) -> list:
    """The level directly below: belts, regions or branches."""
    from apps.organization.models import Belt, Region

    if scope.kind == 'company':
        out = [resolve(f'belt:{b.pk}') for b in Belt.objects.filter(is_active=True)]
        # Branches with no region (headquarters) hang off the company.
        for br in _branches().filter(region__isnull=True):
            out.append(Scope('branch', br.pk, br.name, (br.pk,)))
        return [s for s in out if s.kind == 'branch' or s.branch_ids]
    if scope.kind == 'belt':
        regions = Region.objects.filter(belt_id=scope.id, is_active=True)
        return [s for s in (resolve(f'region:{r.pk}') for r in regions) if s.branch_ids]
    if scope.kind == 'region':
        return [Scope('branch', br.pk, br.name, (br.pk,))
                for br in _branches().filter(region_id=scope.id)]
    return []


def path(scope: Scope) -> list:
    """From the company down to this scope, for the breadcrumb."""
    from apps.organization.models import Region, Branch

    trail = [resolve('company').as_dict()]
    if scope.kind == 'belt':
        trail.append(scope.as_dict())
    elif scope.kind == 'region':
        region = Region.objects.select_related('belt').get(pk=scope.id)
        trail += [{'key': f'belt:{region.belt_id}', 'kind': 'belt',
                   'id': region.belt_id, 'name': region.belt.name}, scope.as_dict()]
    elif scope.kind == 'branch':
        br = Branch.objects.select_related('region__belt').get(pk=scope.id)
        if br.region_id:
            trail += [{'key': f'belt:{br.region.belt_id}', 'kind': 'belt',
                       'id': br.region.belt_id, 'name': br.region.belt.name},
                      {'key': f'region:{br.region_id}', 'kind': 'region',
                       'id': br.region_id, 'name': br.region.name}]
        trail.append(scope.as_dict())
    return trail


def tree() -> dict:
    """The whole ladder at once, for search and quick navigation."""
    def node(s):
        return {**s.as_dict(), 'children': [node(c) for c in children(s)]}
    return node(resolve('company'))
