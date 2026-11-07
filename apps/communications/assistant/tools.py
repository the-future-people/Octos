"""
What Octos's assistant may know: plain facts read from the floor.

Every fact the assistant states must come from one of these tools, and
the checker refuses any reply carrying a price, time, total or status
that didn't. So these return facts only: no wording, no guesses. The
assistant phrases; the tools know.

Each tool returns plain dicts and lists (JSON-ready) to hand to the
language model as tool results.
"""
import logging
from decimal import Decimal
import re
from django.db.models import Q
from django.utils import timezone

logger = logging.getLogger(__name__)

# Work stages in the words a customer would use. Every Job.Work value
# needs a line here; an unknown one is logged and passed through, never
# dropped.
WORK_WORDS = {
    'RECEIVED':      'received, not started yet',
    'IN_PRODUCTION': 'being made now',
    'FINISHING':     'being finished (cutting, binding and so on)',
    'QUALITY_CHECK': 'being checked before it goes out',
    'DONE':          'finished',
}


def branch_hours(branch, at=None):
    """
    Whether a branch is open now, today's hours or why it's closed, and
    when it next opens. From the one calendar (organization/services/hours).
    """
    from apps.organization.services import hours

    at = timezone.localtime(at or timezone.now())
    closed = hours.closed_because(branch, at.date())
    return {
        'branch': _branch_name(branch),
        'open_now': hours.is_open(branch, at),
        'today': (
            {'closed': closed} if closed else
            dict(zip(('opens', 'closes'), map(_clock, hours.hours_on(branch, at.date()))))
        ),
        'next_opening': _when(hours.next_opening(branch, at), at),
    }


def customer_jobs(phone, at=None, limit=5):
    """
    The customer's open jobs (not yet handed over, not voided or
    abandoned, not drafts), newest first, found by their phone number,
    for walk-ins and online orders alike (conversion always sets the
    customer). The money is Job.balance_due, the same figure the cashier
    sees; never a sum of its own.
    """
    from apps.core.phones import lookup_forms
    from apps.customers.models.customer import CustomerProfile
    from apps.jobs.models import Job

    forms = lookup_forms(phone or '')
    if not forms:
        return {'found': False, 'jobs': []}

    people = CustomerProfile.objects.filter(Q(phone__in=forms) | Q(secondary_phone__in=forms))
    jobs = (
        Job.objects
        .filter(Q(customer__in=people) | Q(ordered_by__in=people))
        .exclude(status=Job.DRAFT)
        .exclude(handover_state=Job.Handover.HANDED_OVER)
        .filter(voided_at__isnull=True, abandoned_at__isnull=True)
        .select_related('branch')
        .order_by('-created_at')
        .distinct()[:limit]
    )
    at = timezone.localtime(at or timezone.now())
    found = [_job_facts(job, at) for job in jobs]
    return {'found': bool(found), 'jobs': found}


def _job_facts(job, at):
    work = job.work_state or ''
    words = WORK_WORDS.get(work)
    if words is None:
        logger.warning('Assistant: job %s has a work stage with no words: %r', job.pk, work)
        words = work.replace('_', ' ').lower() or 'unknown'

    balance = job.balance_due
    return {
        'ref': _ref(job.job_number),
        'what': job.line_item_summary,
        'branch': _branch_name(job.branch),
        'stage': words,
        'ready_to_collect': job.handover_state == job.Handover.AWAITING_COLLECTION,
        'out_for_delivery': job.handover_state == job.Handover.OUT_FOR_DELIVERY,
        'promised_ready': _window(job.estimated_ready_at, at) if job.estimated_ready_at else None,
        'promise': (job.promise_state or '').lower() or None,
        'balance_due': f'GHS {balance:.2f}' if balance is not None else None,
        'paid_in_full': job.is_fully_paid,
    }


def _ref(job_number):
    """The short reference a customer can read out: FP-WLB-2026-05629 is 5629."""
    tail = (job_number or '').rsplit('-', 1)[-1].lstrip('0')
    return tail or job_number or ''


def _branch_name(branch):
    name = (getattr(branch, 'name', '') or '').strip()
    return name[:-7] if name.endswith(' Branch') else name


def _clock(t):
    return t.strftime('%I:%M%p').lstrip('0').lower()


def _when(moment, now):
    """'4:10pm today', '8:00am tomorrow', 'Tue 8:00am': short, clear, local."""
    moment = timezone.localtime(moment)
    clock = _clock(moment.time())
    days = (moment.date() - now.date()).days
    if days == 0:
        return f'{clock} today'
    if days == 1:
        return f'{clock} tomorrow'
    return f'{moment:%a} {clock}'


def _window(moment, now):
    """
    A ready time as the customer hears it (7 Nov 2026, Khofi): half an hour,
    starting at the next quarter hour, so it never starts before the floor
    can deliver. 'between 6:30pm and 7:00pm today'. A single time sounds
    more certain than anyone can be.
    """
    from datetime import timedelta
    moment = timezone.localtime(moment)
    start = moment.replace(second=0, microsecond=0)
    start += timedelta(minutes=(-start.minute) % 15)
    if start < moment:
        start += timedelta(minutes=15)
    end = start + timedelta(minutes=30)
    days = (start.date() - now.date()).days
    day = 'today' if days == 0 else 'tomorrow' if days == 1 else f'on {start:%A}'
    return f'between {_clock(start.time())} and {_clock(end.time())} {day}'

# ── Prices ─────────────────────────────────────────────────────────────
# Words that say nothing about which service ("size", "please"), and the
# spellings customers use for what the catalogue spells another way.
SEARCH_STOP = {'the', 'of', 'for', 'and', 'or', 'in', 'on', 'to', 'please', 'pls', 'size', 'sized',
               'want', 'need', 'my', 'me', 'some', 'with', 'how', 'much', 'is', 'price', 'can', 'you'}
SEARCH_SAME = {
    'colour': ('colour', 'color', 'col'), 'color': ('colour', 'color', 'col'),
    'black': ('black', 'b&w', 'bw'), 'white': ('white', 'b&w', 'bw'),
    'us': ('american',), 'usa': ('american',), 'america': ('american',),
    'uk': ('british',), 'britain': ('british',), 'canada': ('canadian',),
    'photos': ('photo',), 'stickers': ('sticker',), 'banners': ('banner',),
    'copies': ('copy',), 'prints': ('print',),
}


def _search_words(query):
    """The customer's words that can tell services apart, each with its other spellings."""
    words = re.findall(r'[a-z0-9&]+', (query or '').lower())
    return [SEARCH_SAME.get(w, (w,)) for w in words if len(w) > 1 and w not in SEARCH_STOP]

def find_services(query, limit=5):
    """
    Services matching what the customer said ("stickers", "A3 colour",
    "binding"), each with what its price needs. The spec fields are the
    service's own spec_template, the same form the counter fills in, so
    Octos asks what the counter would ask, never questions of its own.
    """
    from apps.jobs.models import Service

    words = _search_words(query)
    if not words:
        return {'found': False, 'services': []}

    any_word = Q()
    for alternatives in words:
        for w in alternatives:
            any_word |= (Q(name__icontains=w) | Q(display_name__icontains=w) | Q(code__icontains=w)
                         | Q(variant_label__icontains=w) | Q(description__icontains=w))
    scored = []
    for service in Service.objects.filter(is_active=True).filter(any_word).distinct():
        text = ' '.join([service.name, service.display_name or '', service.code,
                         service.variant_label or '', service.description or '']).lower()
        scored.append((sum(1 for alts in words if any(w in text for w in alts)), service))
    if not scored:
        return {'found': False, 'services': []}

    # Only the closest matches: every service that fits as well as the best
    # one. "American size photo" finds the American passport photo, not
    # plain photo printing; "photo" alone finds all five, and several
    # equally good matches are Octos's cue to ask which one.
    best = max(score for score, _ in scored)
    closest = sorted((s for score, s in scored if score == best), key=lambda s: s.name)[:limit]
    return {'found': True, 'services': [_service_facts(s) for s in closest],
            'several': len(closest) > 1}
def whatsapp_specs(service, specs):
    """
    What Octos may sell on WhatsApp, in a service's terms. A service priced
    by output_mode (passport photos: printed, printed and digital, digital)
    is always quoted printed: digital copies are taken at the front desk
    (decided 6 Nov 2026). Without this the price list has no answer at all.
    """
    from apps.jobs.services.availability import _conditions_of
    specs = dict(specs or {})
    if 'output_mode' in _conditions_of(service) and not specs.get('output_mode'):
        specs['output_mode'] = 'PRINT'
    return specs

def quote(service_code, specifications=None, quantity=1, addon_codes=(), branches=()):
    """
    A price from quote_line, the single quote path the counter and the
    storefront use, at the company-wide rate. Add-ons (binding,
    lamination) through price_addons, as the storefront does.

    An incomplete spec comes back as success False with the engine's own
    reason ("needs a width and a height in inches"): Octos's cue to ask,
    never to guess. branches, if given, are checked with can_make, so a
    price is never offered where the job can't be made.
    """
    from apps.jobs.models import Service
    from apps.jobs.pricing_engine import quote_line
    from apps.jobs.services.availability import can_make, price_addons

    service = Service.objects.filter(code=service_code, is_active=True).first()
    if service is None:
        return {'success': False, 'error': f'No active service with code {service_code!r}.'}

    specs = whatsapp_specs(service, specifications)
    quantity = max(1, int(quantity or 1))
    line = quote_line(service, None, specs, quantity)
    if not line.get('success'):
        return {'success': False, 'error': line.get('error') or 'Could not price this.',
                'needs': _spec_fields(service)}

    total = line['total']
    addons_out = []
    if addon_codes:
        # Every add-on asked for must exist, or the quote is refused: a code
        # that matched nothing would otherwise vanish, and a price for "bound"
        # would arrive with no binding in it.
        found = dict(
            Service.objects.filter(code__in=addon_codes, is_active=True).values_list('code', 'pk')
        )
        missing = [code for code in addon_codes if code not in found]
        if missing:
            return {'success': False, 'error': f"Not offered: {', '.join(missing)}."}
        priced, addons_total, problem = price_addons(service, list(found.values()), quantity, specs)
        if problem:
            return {'success': False, 'error': problem}
        total += addons_total
        # price_addons returns each total as a string, with the name under
        # 'service_name' and, for binding, the ring size in 'detail'.
        addons_out = [
            {'name': p['service_name'], 'detail': p.get('detail'),
             'total': f"GHS {Decimal(p['total']):.2f}"}
            for p in priced
        ]

    # When it could be ready, read from the floor now (7 Nov 2026, Khofi):
    # the prediction the counter's New Job window asks, at the branch that
    # would make it, said as a half-hour window. An estimate while quoting;
    # the promise is fixed once the order is paid.
    ready, ready_note = None, 'The team will confirm the ready time.'
    try:
        from apps.organization.models import Branch
        from apps.production.services.prediction_service import PredictionService
        maker = next(iter(branches or ()), None) or Branch.objects.filter(is_trading=True, is_active=True).first()
        if maker is not None:
            pages = max(1, int(specs.get('pages') or 1))
            ready_at = PredictionService(maker).predict([(service, quantity, pages)]).ready_at
            if ready_at:
                ready = f'{_window(ready_at, timezone.now())} at {_branch_name(maker)}'
                ready_note = 'An estimate from the floor now; it is fixed once the order is paid.'
    except Exception:
        import logging
        logging.getLogger(__name__).warning('Could not read the floor for a quote', exc_info=True)

    facts = {
        'success': True,
        'service': service.name,
        'variant': service.variant_label or None,
        'quantity': quantity,
        'unit_price': f"GHS {line['unit_price']:.2f}",
        # The item's own total before add-ons, so an itemised answer is verifiable.
        'item_total': f"GHS {line['total']:.2f}",
        'addons': addons_out,
        'ready': ready,
        'ready_note': ready_note,
        'total': f'GHS {total:.2f}',
    }
    if line.get('minimum_applied'):
        facts['minimum_charge'] = f"GHS {line['minimum']}"
        facts['minimum_covers_up_to'] = line.get('covers_up_to')
    if branches:
        facts['can_make_at'] = [_branch_name(b) for b in branches if can_make(service, b)]
    return facts


def _service_facts(service):
    return {
        'code': service.code,
        # Variants share a display name ("Colour Printing"), so the service's
        # own name and its variant label tell them apart; with only the
        # display name, one-sided and front-and-back look like a conflict.
        'name': service.name,
        'variant': service.variant_label or None,
        # What one unit is ("a set of 4 passport photos"), so a price is
        # quoted in the right units.
        'about': service.description or '',
        'unit': (service.unit or '').replace('PER_', '').lower(),
        'needs_file': bool(service.requires_file_upload),
        'needs_design': bool(service.requires_design),
        'needs': _spec_fields(service),
        # Binding, lamination and so on: the codes quote() takes as addon_codes.
        'addons': [
            {'code': a.code, 'name': a.display_name or a.name}
            for a in service.addons.filter(is_active=True)
        ],
    }


def _spec_fields(service):
    """What a price needs, from the service's own spec form: key, label, choices."""
    fields = []
    for field in service.spec_template or []:
        if not isinstance(field, dict) or not field.get('key'):
            continue
        entry = {
            'key': field['key'],
            'label': field.get('label') or field['key'],
            'required': bool(field.get('required')),
        }
        for extra in ('type', 'options', 'default', 'min'):
            if field.get(extra) not in (None, ''):
                entry[extra] = field[extra]
        fields.append(entry)
    return fields