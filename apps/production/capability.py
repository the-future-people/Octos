"""
Which branches can do this work, and when each would finish.

Not the reroute engine in apps/jobs. That one moves a job that already
has a home, scores branches on capacity and queue depth, and assumes an
origin to route away from. An order placed online has no origin, and the
question it asks is narrower: who can print this, and when.

So this answers only that, and answers it honestly. A branch appears
when it genuinely can do the work today — it has the machine, the
machine is working, and the material fits. It does not appear with a
low score; it does not appear at all.

The ranking is by time, soonest first, because that is the one thing we
know. Whether sooner matters more than nearer is the customer's
judgement, not ours, so both travel with each option and they choose —
the way a rider picks between a cheap car ten minutes away and a nearer
one that costs more.

When nothing qualifies, the reasons come back too. An empty list tells
a customer nothing; "no branch can print a banner that wide today"
tells them what to change.
"""

import logging
from decimal import Decimal

logger = logging.getLogger(__name__)

# Rough metres per degree of latitude. Good enough to order three
# branches by distance within one city, and honest about being an
# approximation rather than a road distance.
METRES_PER_DEGREE = 111_320


def assess(line_items, width_mm=None, customer_location=None, at=None):
    """
    The full answer: what can be done where, and why not elsewhere.

    line_items is a list of (service, quantity, pages), the same shape
    PredictionService takes.

    Returns {'options': [...], 'refusals': [...]}, options soonest
    first.
    """
    from apps.organization.models import Branch

    services = [service for service, _, _ in line_items]
    options, refusals = [], []

    branches = Branch.objects.filter(is_active=True).select_related('region')

    for branch in branches:
        problem = _why_not(branch, services, width_mm)
        if problem:
            refusals.append({
                'branch': branch,
                'branch_name': branch.name,
                'reason': problem,
            })
            continue

        prediction = _predict(branch, line_items, at)
        if prediction is None:
            refusals.append({
                'branch': branch,
                'branch_name': branch.name,
                'reason': 'We could not work out a time for this branch.',
            })
            continue

        options.append({
            'branch': branch,
            'branch_id': branch.id,
            'branch_name': branch.name,
            'branch_code': branch.code,
            'address': branch.address,
            'ready_at': prediction.ready_at,
            'minutes': prediction.total_minutes,
            'is_next_day': prediction.is_next_day,
            'confidence': prediction.confidence,
            'distance_m': _distance(branch, customer_location),
        })

    # Soonest first. Where two land at the same moment, the nearer one
    # wins — but only as a tiebreak, since we do not know whether this
    # customer is collecting or has it delivered.
    options.sort(key=lambda o: (
        o['ready_at'],
        o['distance_m'] if o['distance_m'] is not None else float('inf'),
    ))

    return {'options': options, 'refusals': refusals}


def branch_options(line_items, width_mm=None, customer_location=None, at=None):
    """Just the options, for callers that do not need the refusals."""
    return assess(
        line_items, width_mm=width_mm,
        customer_location=customer_location, at=at,
    )['options']


def _why_not(branch, services, width_mm):
    """
    The reason this branch cannot take the work, or None if it can.

    Written as a sentence a customer could read. The branch that cannot
    print a wide banner today is not a failure of the system, and the
    message should not read like one.
    """
    from apps.production.models import Machine, ServiceStation

    for service in services:
        routes = ServiceStation.objects.filter(
            service=service,
        ).select_related('machine_type')

        if not routes.exists():
            return f'We have not set up {service.name} on the floor yet.'

        for route in routes:
            if route.machine_type_id is None:
                # Hand work. Any branch with people can do it.
                continue

            machines = Machine.objects.filter(
                branch=branch,
                machine_type=route.machine_type,
                is_active=True,
            )

            if not machines.exists():
                return (
                    f'{branch.name} does not have the machine for '
                    f'{service.name}.'
                )

            working = machines.filter(is_available=True)
            if not working.exists():
                return (
                    f'The machine for {service.name} at {branch.name} is '
                    f'out of service today.'
                )

            if width_mm:
                widest = max((m.max_width_mm or 0) for m in working)
                if widest and width_mm > widest:
                    return (
                        f'{branch.name} can print up to {widest}mm wide. '
                        f'This job needs {int(width_mm)}mm.'
                    )

    return None


def _predict(branch, line_items, at):
    """
    When this branch would finish. None where it cannot say.

    A prediction failing must not take the whole answer down with it:
    one branch that cannot be timed should not hide the two that can.
    """
    from apps.production.services.prediction_service import PredictionService

    try:
        return PredictionService(branch).predict(line_items, at=at)
    except Exception:
        logger.warning(
            'Could not predict for %s', branch.code, exc_info=True,
        )
        return None


def _distance(branch, customer_location):
    """
    Roughly how far the branch is, in metres.

    Straight-line, not by road, and None when either end is unknown —
    which is the common case today, since the storefront asks for a
    phone number and not an address. A number we cannot stand behind is
    worse than no number, so the field travels empty rather than
    guessed.
    """
    if not customer_location:
        return None
    if branch.latitude is None or branch.longitude is None:
        return None

    try:
        import math

        lat1 = float(branch.latitude)
        lon1 = float(branch.longitude)
        lat2 = float(customer_location['latitude'])
        lon2 = float(customer_location['longitude'])
    except (KeyError, TypeError, ValueError):
        return None

    # Degrees of longitude narrow towards the poles; at Accra's latitude
    # the correction is small but costs nothing to make.
    dy = (lat2 - lat1) * METRES_PER_DEGREE
    dx = (lon2 - lon1) * METRES_PER_DEGREE * math.cos(math.radians((lat1 + lat2) / 2))

    return round(math.hypot(dx, dy))