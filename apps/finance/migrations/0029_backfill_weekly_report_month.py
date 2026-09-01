from django.db import migrations


def set_month_from_date_from(apps, schema_editor):
    """
    Every existing report already sits inside a single month: prepare()
    clipped date_from and date_to to the month boundary, which is why a
    week straddling one produced a report covering only part of it.

    So the month is simply the month of date_from, and no row is ambiguous.
    """
    WeeklyReport = apps.get_model('finance', 'WeeklyReport')
    updated = 0
    for report in WeeklyReport.objects.filter(month__isnull=True):
        report.month = report.date_from.month
        report.save(update_fields=['month'])
        updated += 1
    print(f'  backfilled month on {updated} weekly report(s)')


def clear_month(apps, schema_editor):
    WeeklyReport = apps.get_model('finance', 'WeeklyReport')
    WeeklyReport.objects.update(month=None)


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0028_alter_weeklyreport_options_and_more'),
    ]

    operations = [
        migrations.RunPython(set_month_from_date_from, clear_month),
    ]