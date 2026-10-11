"""
python manage.py seed_test_orders

Three paid orders to look at, with real line items, real prices and
real artwork records. Westland, since it is the only branch trading.

They sit at Paid, because that is as far as an order can honestly get
today — conversion is not built, so no job exists and the floor has
never heard of them. The tracking page will show them at the first
stage with the rest greyed, which is the truth.

Once conversion exists these same orders carry on through the stages
without being remade.

The numbers printed at the end are what to type into the tracking page.
"""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.jobs.models import Service
from apps.organization.models import Branch
from apps.storefront.models import Lead, OnlineOrder
from apps.storefront.services.fees import split_payment


ORDERS = [
    {
        'who': ('0244111222', 'Adwoa'),
        'lines': [
            ('BIZ-CARDS', 200, {
                'size': 'Standard (85×54mm)',
                'paper_stock': 'Matte 350gsm',
                'sides': 'Double-sided',
            }),
        ],
    },
    {
        'who': ('0244333444', 'Kwame'),
        'lines': [
            ('SAV', 2, {'width_in': 24, 'height_in': 24}),
        ],
    },
    {
        'who': ('0244555666', 'Esi'),
        'lines': [
            ('FLEXY', 1, {'width_in': 96, 'height_in': 48}),
        ],
    },
]


class Command(BaseCommand):
    help = 'Creates a few paid test orders to look at on the tracking page'

    def handle(self, *args, **options):
        from apps.jobs.pricing_engine import quote_line

        branch = Branch.objects.filter(code='WLB').first()
        if branch is None:
            self.stderr.write('No Westland branch. Nothing to attach these to.')
            return

        made = []

        for spec in ORDERS:
            phone, name = spec['who']
            lead, _ = Lead.objects.get_or_create(
                phone=phone, defaults={'first_name': name},
            )

            priced = []
            total = Decimal('0.00')
            skipped = False

            for code, quantity, specifications in spec['lines']:
                service = Service.objects.filter(code=code, is_active=True).first()
                if service is None:
                    self.stdout.write(f'  {code} is not in the catalogue — skipped')
                    skipped = True
                    break

                quote = quote_line(
                    service=service, branch=None,
                    specifications=specifications, quantity=quantity,
                )
                if not quote.get('success'):
                    self.stdout.write(
                        f'  {code} would not price: {quote.get("error")}'
                    )
                    skipped = True
                    break

                priced.append({
                    'id': f'{code.lower()}-{timezone.now().timestamp():.0f}'[:12],
                    'service': service.id,
                    'service_name': service.name,
                    'quantity': quantity,
                    'specifications': specifications,
                    'unit_price': str(quote.get('unit_price') or quote['total']),
                    'total': str(quote['total']),
                })
                total += Decimal(str(quote['total']))

            if skipped:
                continue

            gross, fee, net = split_payment(total)

            order = OnlineOrder.objects.create(
                lead=lead,
                branch=branch,
                line_items=priced,
                full_total=total,
                total=total,
                status=OnlineOrder.Status.PAID,
                payment_reference=f'TEST-{timezone.now().timestamp():.0f}',
                payment_fee=fee,
                net_received=net,
                paid_at=timezone.now(),
            )
            order.touch_expiry()
            order.save(update_fields=['expires_at'])

            made.append((order, name))

        if not made:
            self.stderr.write('Nothing was created.')
            return

        self.stdout.write(self.style.SUCCESS(f'\n{len(made)} order(s) made:\n'))
        for order, name in made:
            self.stdout.write(f'  {order.order_number}  {name}')
            self.stdout.write(f'    GHS {order.total}')
            self.stdout.write(
                f'    /track/{order.order_number}?t={order.access_token}\n'
            )