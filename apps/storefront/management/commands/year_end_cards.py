"""
Send the year-end thank-you cards.

  python manage.py year_end_cards                      dry run: who gets what, and the cost
  python manage.py year_end_cards --test 0556244194     one real card to that phone (a sample customer's year)
  python manage.py year_end_cards --send                everyone registered, once each

Safe to run again: a number whose card was already accepted by mNotify
is skipped, so a send that stops halfway can simply be restarted.
"""

import time

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = 'Year-end thank-you cards: dry run, test, or send.'

    def add_arguments(self, parser):
        parser.add_argument('--year', type=int, default=timezone.localdate().year)
        parser.add_argument('--test', metavar='PHONE', help='Send one card to this phone.')
        parser.add_argument('--as-customer', type=int, help='With --test: whose year to show.')
        parser.add_argument('--send', action='store_true', help='Send to everyone registered.')
        parser.add_argument('--pause', type=float, default=0.4, help='Seconds between texts.')

    def handle(self, *args, **opts):
        from apps.customers.models import CustomerProfile
        from apps.storefront.models import TextMessage, YearCard
        from apps.storefront.services.sms import send_sms
        from apps.storefront.services import year_card as yc

        year = opts['year']
        kind = yc.text_kind(year)

        if opts['test']:
            if opts['as_customer']:
                customer = CustomerProfile.objects.get(pk=opts['as_customer'])
            else:
                customer = (CustomerProfile.objects.filter(jobs__created_at__year=year)
                            .exclude(jobs__status__in=yc.DEAD).distinct().first()
                            or CustomerProfile.objects.first())
            card = yc.card_for(customer, year)
            text = yc.card_text(card)
            ok = send_sms(opts['test'], text, kind=f'{kind}-test')
            self.stdout.write(f'Test card ({card.kind}, {customer}) to {opts["test"]}: '
                              f'{"sent" if ok else "NOT accepted"}\n  {text}\n  ({len(text)} characters)')
            return

        people = list(yc.recipients())
        done = set(TextMessage.objects.filter(kind=kind, accepted=True).values_list('phone', flat=True))
        todo = [(c, n) for c, n in people if n not in done]

        if not opts['send']:
            ordered = sum(1 for c, _ in todo if yc.year_of(c, year))
            self.stdout.write(
                f'DRY RUN for {year}: {len(people)} registered, {len(done)} already sent, {len(todo)} to send.\n'
                f'  {ordered} get their year, {len(todo) - ordered} get the thank-you card.\n'
                f'  About {len(todo)} SMS credits. Nothing was sent.\n'
                f'  Test first:  python manage.py year_end_cards --test YOUR_PHONE\n'
                f'  Then send:   python manage.py year_end_cards --send')
            return

        sent = refused = 0
        for c, number in todo:
            card = yc.card_for(c, year)
            if send_sms(number, yc.card_text(card), kind=kind):
                sent += 1
                YearCard.objects.filter(pk=card.pk).update(sent_at=timezone.now())
            else:
                refused += 1
            time.sleep(opts['pause'])
        self.stdout.write(f'Sent {sent}, not accepted {refused}, skipped {len(done)} already sent.')
