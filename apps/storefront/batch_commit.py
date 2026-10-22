"""
Several files, each with its sets, added to an order in one go.

POST /api/v1/storefront/commit/batch/
    {
      idempotency_key, order?, token?,
      specifications,                       # the settings the files were checked with
      files: [{
        artwork_token, checked_service,     # the file, and the service it was checked on
        sets: [{ service, quantity, page_selection?, addons? }]
      }]
    }

A set is a bundle: some or all of a file's pages, in colour or black and
white, one side or both, so many copies, with its own finishing. Each set
is its own line.

The same rules as a single commit, applied to all of it at once:

- each file is checked once, against the service it was checked on, and
  a set may only use a service of that file's family (its sides and its
  black-and-white twin), never an unrelated product;
- each set's pages are checked against the file and priced from their
  own count, never the whole file's;
- every line is added and the order re-priced in one transaction, all or
  nothing, under one idempotency key, so a dropped connection or a second
  press never leaves half an order or a second copy;
- each line gets its own copy of the file; the staged upload goes only
  once every line has one. (A single commit moves the file onto its one
  line, which is why the second set of a file used to be refused.)
"""

from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Q
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

MAX_FILES = 15
MAX_LINES = 60


def _family_ids(service):
    """The service, its sides, and its black-and-white (or colour) twins."""
    from apps.jobs.models import Service

    def siblings(s):
        base = getattr(s, 'variant_of_id', None) or s.pk
        return set(Service.objects.filter(Q(pk=base) | Q(variant_of_id=base)).values_list('pk', flat=True))

    ids = siblings(service)
    twins = set(Service.objects.filter(pk__in=ids, bw_counterpart__isnull=False)
                .values_list('bw_counterpart', flat=True))
    twins |= set(Service.objects.filter(bw_counterpart__in=ids).values_list('pk', flat=True))
    for twin in Service.objects.filter(pk__in=twins):
        ids |= siblings(twin)
    return ids


def _attach_copies(order, line_ids, staged):
    """Each line its own copy of the file; the staged upload goes after."""
    from apps.storefront.models import OrderFile

    for line_id in line_ids:
        record = OrderFile(
            order=order, line_id=line_id,
            original_filename=staged.original_filename,
            size_bytes=staged.size_bytes, content_type=staged.content_type,
            verdict=staged.verdict, checks=staged.checks,
            warning_accepted=staged.verdict == 'warn',
            **staged.measured(),
        )
        staged.file.open('rb')
        staged.file.seek(0)
        record.file.save(staged.original_filename, staged.file, save=False)
        record.save()
    staged.file.close()
    staged.file.delete(save=False)
    staged.delete()


class BatchCommitView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'storefront'

    def post(self, request):
        from apps.jobs.models import Service
        from apps.jobs.services.availability import counts_pages, sheets_for
        from apps.storefront.models import CommitRecord, OnlineOrder
        from apps.storefront.services.page_sets import SelectionRefused, format_selection, parse_selection
        from apps.storefront.views import (
            OrderDetailView, _order_or_404, _quantity_problem, _Refused, _staged_for,
        )

        def refuse(message, code=status.HTTP_400_BAD_REQUEST):
            return Response({'detail': message}, status=code)

        key = (request.data.get('idempotency_key') or '').strip()
        if not key:
            return refuse('This request needs an idempotency key.')
        done = CommitRecord.objects.filter(idempotency_key=key).first()
        if done is not None:
            return Response(done.result, status=status.HTTP_200_OK)

        files = request.data.get('files') or []
        if not isinstance(files, list) or not files:
            return refuse('Add a file first.')
        if len(files) > MAX_FILES:
            return refuse(f'{MAX_FILES} files at most at once.')
        base_specs = request.data.get('specifications') or {}

        order_number = (request.data.get('order') or '').strip()
        order = None
        if order_number:
            order = _order_or_404(order_number, request.data.get('token'))
            if not order.is_open:
                return refuse('That order has been paid for. Starting another is the way to order something else.',
                              status.HTTP_409_CONFLICT)

        # ── Check every file and every set before anything is made ──
        planned = []   # (staged, [line dicts])
        line_total = 0
        for f in files:
            checked = Service.objects.filter(pk=f.get('checked_service'), is_active=True).first()
            if checked is None:
                return refuse('That service is not available.')
            staged, refusal = _staged_for(f.get('artwork_token'), checked, base_specs)
            if refusal:
                return refuse(refusal)
            family = _family_ids(checked)
            sets = f.get('sets') or []
            if not sets:
                return refuse('Each file needs at least one set.')
            lines = []
            for s in sets:
                service = Service.objects.filter(pk=s.get('service'), is_active=True).first()
                if service is None or service.pk not in family:
                    return refuse(f'{staged.original_filename}: that is not a way this file can be printed.')
                quantity = int(s.get('quantity') or 1)
                problem = _quantity_problem(service, quantity)
                if problem:
                    return refuse(problem)
                specs = dict(base_specs)
                if counts_pages(service):
                    selection = s.get('page_selection')
                    if selection:
                        try:
                            chosen = parse_selection(selection, staged.page_count or 1)
                        except SelectionRefused as refused:
                            return refuse(f'{staged.original_filename}: {refused}')
                        specs.update(page_selection=format_selection(chosen),
                                     pages=sheets_for(service, len(chosen)))
                    else:
                        specs['pages'] = sheets_for(service, staged.page_count)
                lines.append({'service': service.pk, 'quantity': quantity,
                              'specifications': specs, 'addons': s.get('addons') or []})
            line_total += len(lines)
            planned.append((staged, lines))
        if line_total > MAX_LINES:
            return refuse(f'That is more than {MAX_LINES} items at once. Send them in two goes.')

        # ── Make it real: all of it, or none ─────────────────────────
        try:
            with transaction.atomic():
                if order is None:
                    order = OnlineOrder.objects.create()
                existing = list(order.line_items or [])
                new_lines = [line for _, lines in planned for line in lines]
                priced, total, error = OrderDetailView._price(
                    existing + new_lines,
                    {l.get('service'): l.get('id') for l in existing if l.get('id')},
                )
                if error:
                    raise _Refused(error)
                order.line_items = priced
                order.total = total
                order.touch_expiry()
                order.save()

                # The new lines are the last ones, in the order they were sent.
                new_ids = [l['id'] for l in priced[len(existing):]]
                at = 0
                for staged, lines in planned:
                    _attach_copies(order, new_ids[at:at + len(lines)], staged)
                    at += len(lines)

                result = {
                    'order_number': order.order_number,
                    'access_token': order.access_token,
                    'line_ids': new_ids,
                    'line_count': len(priced),
                    'total': f'{Decimal(order.total):.2f}',
                }
                CommitRecord.objects.create(idempotency_key=key, order=order, result=result)
        except _Refused as refused:
            return refuse(str(refused))
        except IntegrityError:
            done = CommitRecord.objects.filter(idempotency_key=key).first()
            if done is not None:
                return Response(done.result, status=status.HTTP_200_OK)
            raise

        return Response(result, status=status.HTTP_201_CREATED)