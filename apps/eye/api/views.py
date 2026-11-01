"""
/api/v1/eye/ — read-only, owner-only.

Every lens takes the same query: ?scope=company|belt:ID|region:ID|branch:ID
&day=YYYY-MM-DD (default today) &period=today|week|month (where it has one).
Answers are cached briefly so the network stays quick while the owner
clicks around; the figures are never more than CACHE_SECONDS old.
"""

import datetime
import hashlib
from decimal import Decimal

from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.eye.api.permissions import IsBusinessOwner
from apps.eye.services import (alerts, customers, health, jobs, machines, money,
                               online, overview, people, periods)
from apps.eye.services import scope as scope_mod

CACHE_SECONDS = 30


def clean(value):
    """Decimals as numbers and dates as ISO text, all the way down."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    return value


class EyeView(APIView):
    permission_classes = [IsAuthenticated, IsBusinessOwner]

    def compute(self, request, **kwargs):
        raise NotImplementedError

    def get(self, request, **kwargs):
        key = 'eye:' + hashlib.sha1(
            f'{request.path}?{request.GET.urlencode()}'.encode()).hexdigest()
        data = cache.get(key)
        if data is None:
            try:
                data = clean(self.compute(request, **kwargs))
            except scope_mod.ScopeNotFound:
                return Response({'detail': 'No such place.'}, status=404)
            except ObjectDoesNotExist:
                return Response({'detail': 'Not found.'}, status=404)
            cache.set(key, data, CACHE_SECONDS)
        return Response(data)

    # Shared query parsing
    def sc(self, request):
        return scope_mod.resolve(request.GET.get('scope'))

    def day(self, request):
        return periods.parse_day(request.GET.get('day'))

    def window(self, request):
        name = request.GET.get('period', 'today')
        name = name if name in periods.PERIODS else 'today'
        return name, periods.window(name, self.day(request))


class MeView(EyeView):
    def compute(self, request):
        u = request.user
        return {'name': u.full_name, 'first_name': u.first_name, 'owner': True}


class TreeView(EyeView):
    def compute(self, request):
        return scope_mod.tree()


class OverviewView(EyeView):
    def compute(self, request):
        return overview.build(self.sc(request), self.day(request))


class PeopleView(EyeView):
    def compute(self, request):
        sc = self.sc(request)
        return {'scope': sc.as_dict(), 'path': scope_mod.path(sc),
                'children': [c.as_dict() for c in scope_mod.children(sc)],
                'alerts': [a for a in alerts.compute(sc, self.day(request)) if a['lens'] == 'people'],
                **people.lens(sc, self.day(request))}


class PersonView(EyeView):
    def compute(self, request, pk):
        return people.person(pk, self.day(request))


class MoneyView(EyeView):
    def compute(self, request):
        sc = self.sc(request)
        name, (first, last, pf, pl, label) = self.window(request)
        return {'scope': sc.as_dict(), 'path': scope_mod.path(sc), 'period': name,
                'compared_with': label,
                'alerts': [a for a in alerts.compute(sc, self.day(request))
                           if a['lens'] in ('money', 'customers') and a['kind'] in ('sheet_open', 'credit_limit')],
                **money.lens(sc, first, last, pf, pl)}


class JobsView(EyeView):
    def compute(self, request):
        sc = self.sc(request)
        name, (first, last, pf, pl, label) = self.window(request)
        return {'scope': sc.as_dict(), 'path': scope_mod.path(sc), 'period': name,
                'compared_with': label,
                'children': [c.as_dict() for c in scope_mod.children(sc)],
                'alerts': [a for a in alerts.compute(sc, self.day(request))
                           if a['lens'] in ('jobs', 'health')],
                **jobs.lens(sc, first, last, pf, pl)}


class JobView(EyeView):
    def compute(self, request, pk):
        return jobs.journey(pk)


class MachinesView(EyeView):
    def compute(self, request):
        sc = self.sc(request)
        return {'scope': sc.as_dict(), 'path': scope_mod.path(sc),
                'children': [c.as_dict() for c in scope_mod.children(sc)],
                'alerts': [a for a in alerts.compute(sc, self.day(request)) if a['lens'] == 'machines'],
                **machines.lens(sc, self.day(request))}


class MachineView(EyeView):
    def compute(self, request, pk):
        return machines.machine(pk, self.day(request))


class CustomersView(EyeView):
    def compute(self, request):
        sc = self.sc(request)
        name, (first, last, pf, pl, label) = self.window(request)
        return {'scope': sc.as_dict(), 'path': scope_mod.path(sc), 'period': name,
                'alerts': [a for a in alerts.compute(sc, self.day(request)) if a['lens'] == 'customers'],
                **customers.lens(sc, first, last)}


class CustomerView(EyeView):
    def compute(self, request, pk):
        return customers.customer(pk)


class OnlineView(EyeView):
    def compute(self, request):
        sc = self.sc(request)
        name, (first, last, pf, pl, label) = self.window(request)
        return {'scope': sc.as_dict(), 'period': name, 'compared_with': label,
                **online.lens(sc, first, last, pf, pl)}


class AppView(EyeView):
    def compute(self, request):
        name, (first, last, pf, pl, label) = self.window(request)
        return {'period': name, 'compared_with': label, **online.app(first, last, pf, pl)}


class HealthView(EyeView):
    def compute(self, request):
        return health.lens()


class InventoryView(EyeView):
    def compute(self, request):
        sc = self.sc(request)
        return {'scope': sc.as_dict(), 'state': 'NOT_COUNTED',
                'note': 'No branch has done a first stock count yet.'}
