"""
Management command: generate_sheet_pdf

Usage:
    python manage.py generate_sheet_pdf --sheet-id 213
    python manage.py generate_sheet_pdf --branch WLB --date 2026-04-28

The drawing lives in apps/finance/pdf/sheet_pdf.py, beside the other
document builders. This file is the command-line wrapper around it.
Output saved to: media/sheets/sheet_<id>_<date>.pdf
"""

import os
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.conf import settings

from apps.finance.models import DailySalesSheet
from apps.organization.models import Branch
from apps.finance.pdf.sheet_pdf import build_data, build_pdf


# ═══════════════════════════════════════════════════════════
# MANAGEMENT COMMAND
# ═══════════════════════════════════════════════════════════

class Command(BaseCommand):
    help = 'Generate a 3-page read-only PDF for a closed daily sales sheet'

    def add_arguments(self, parser):
        parser.add_argument('--branch',   type=str, help='Branch code e.g. WLB')
        parser.add_argument('--date',     type=str, help='Date YYYY-MM-DD')
        parser.add_argument('--sheet-id', type=int, help='Direct sheet ID')
        parser.add_argument('--output',   type=str, help='Output path (optional)')

    def handle(self, *args, **options):
        sheet       = self._get_sheet(options)
        output_path = self._resolve_output(sheet, options.get('output'))

        self._ensure_assets()
        data = build_data(sheet)
        build_pdf(data, output_path)

        self.stdout.write(self.style.SUCCESS(f'PDF generated: {output_path}'))

    def _get_sheet(self, options):
        if options.get('sheet_id'):
            try:
                return DailySalesSheet.objects.select_related(
                    'branch', 'opened_by', 'closed_by'
                ).get(pk=options['sheet_id'])
            except DailySalesSheet.DoesNotExist:
                raise CommandError(f"Sheet {options['sheet_id']} not found.")

        branch_code = options.get('branch')
        if not branch_code:
            raise CommandError('Provide --branch or --sheet-id.')

        try:
            branch = Branch.objects.get(code=branch_code.upper())
        except Branch.DoesNotExist:
            raise CommandError(f"Branch '{branch_code}' not found.")

        date_str = options.get('date')
        if date_str:
            try:
                from datetime import datetime as dt
                target_date = dt.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                raise CommandError('Date must be YYYY-MM-DD.')
        else:
            target_date = timezone.localdate()

        try:
            return DailySalesSheet.objects.select_related(
                'branch', 'opened_by', 'closed_by'
            ).get(branch=branch, date=target_date)
        except DailySalesSheet.DoesNotExist:
            raise CommandError(
                f"No sheet for {branch.name} on {target_date}.")

    def _resolve_output(self, sheet, custom_path):
        if custom_path:
            return custom_path
        sheets_dir = os.path.join(MEDIA_ROOT, 'sheets')
        os.makedirs(sheets_dir, exist_ok=True)
        return os.path.join(sheets_dir,
            f"sheet_{sheet.pk}_{sheet.date}.pdf")

    def _ensure_assets(self):
        """Check logo assets exist in media/assets/."""
        assets_dir = os.path.join(MEDIA_ROOT, 'assets')
        os.makedirs(assets_dir, exist_ok=True)
        if not os.path.exists(LOGO_WHITE):
            raise CommandError(
                f"White logo not found at {LOGO_WHITE}. "
                f"Copy farhat_logo_white.png to media/assets/.")
        if not os.path.exists(LOGO_COLOR):
            raise CommandError(
                f"Colour logo not found at {LOGO_COLOR}. "
                f"Copy farhat_logo_color.jpg to media/assets/.")
