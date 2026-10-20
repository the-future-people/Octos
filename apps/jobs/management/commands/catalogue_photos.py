"""
Put a photo on each service, in the public catalogue bucket.

    python manage.py catalogue_photos --dry-run
    python manage.py catalogue_photos
    python manage.py catalogue_photos --replace

Photos come from catalogue_photos/ at the root of the project, matched
to services by name the same way the storefront matches them: most
specific first. A service whose saved photo no longer exists (lost in
the move to R2) is cleared and given one if a photo matches. Services
that already have a working photo are left alone unless --replace.

Also mends the mangled dashes ("???" where an em dash should be) in
service descriptions.
"""

from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand

# Most specific first: "pull-up banner" before "banner", "A4 Lamination"
# before plain "A4", black and white before colour.
RULES = [
    (['pull-up', 'pull up', 'roll-up', 'roll up'], 'pull-up-banner.jpg'),
    (['flexy', 'banner', 'flex'], 'flexy-banner.jpg'),
    (['sav', 'sticker', 'label', 'vinyl'], 'sav-sticker.jpg'),
    (['id card', 'id-card'], 'id-cards.jpg'),
    (['business card', 'biz-card', 'complimentary'], 'business-cards.jpg'),
    (['letterhead'], 'letterheads.jpg'),
    (['flyer', 'leaflet'], 'flyers.jpg'),
    (['passport'], 'passport-photos.jpg'),
    (['book', 'magazine'], 'books.jpg'),
    (['dtf'], 'dtf.jpg'),
    (['embroider'], 'embroidery.jpg'),
    (['laminat'], 'lamination.jpg'),
    (['slide binding', 'slide-binding'], 'slide-binding.jpg'),
    (['binding', 'comb'], 'ring-binding.jpg'),
    (['a3 b&w', 'a3 black'], 'a3-bw.jpg'),
    (['a3'], 'a3-colour.jpg'),
    (['a4 b&w', 'a4 black', 'black & white', 'black and white'], 'a4-bw.jpg'),
    (['a4 colo', 'a4'], 'a4-colour.jpg'),
]


def photo_for(name):
    n = (name or '').lower()
    for words, photo in RULES:
        if any(w in n for w in words):
            return photo
    return None


class Command(BaseCommand):
    help = 'Give each service a photo from catalogue_photos/, in the public bucket.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--replace', action='store_true', help='Replace photos that already work.')

    def handle(self, *args, dry_run=False, replace=False, **options):
        from apps.jobs.models import Service

        folder = Path(settings.BASE_DIR) / 'catalogue_photos'
        if not folder.is_dir():
            self.stderr.write(f'No folder at {folder}.')
            return

        given = cleared = kept = mended = 0
        for service in Service.objects.all().order_by('name'):
            changed = []

            if service.description and '???' in service.description:
                changed.append('description mended')
                if not dry_run:
                    service.description = service.description.replace(' ??? ', ' — ').replace('???', '—')
                    service.save(update_fields=['description'])
                mended += 1

            has = bool(service.image)
            works = has and service.image.storage.exists(service.image.name)
            photo = photo_for(f'{service.name} {service.code}')
            path = folder / photo if photo else None

            if works and not replace:
                kept += 1
            elif path and path.is_file():
                changed.append(f'photo {photo}')
                if not dry_run:
                    with open(path, 'rb') as handle:
                        service.image.save(photo, File(handle), save=True)
                given += 1
            elif has and not works:
                changed.append('broken photo cleared')
                if not dry_run:
                    service.image = None
                    service.save(update_fields=['image'])
                cleared += 1

            if changed:
                self.stdout.write(f'  {service.code}: {", ".join(changed)}')

        verb = 'Would give' if dry_run else 'Gave'
        self.stdout.write(self.style.SUCCESS(
            f'{verb} {given} photo(s); cleared {cleared} broken; kept {kept} working; '
            f'mended {mended} description(s).' + (' Dry run: nothing kept.' if dry_run else '')
        ))