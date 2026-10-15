from django.db import migrations, models


def mark_by_hand(apps, schema_editor):
    """
    Steps made before this field existed: by hand where their route names
    no machine type. Before, a by-hand step at a station that also has
    machines (cutting a banner, though there is a plotter) was left
    unassigned and could never start.
    """
    JobStep = apps.get_model('jobs', 'JobStep')
    ServiceStation = apps.get_model('production', 'ServiceStation')

    by_hand_routes = set(
        ServiceStation.objects
        .filter(machine_type__isnull=True)
        .values_list('service_id', 'station_id')
    )
    count = 0
    for step in JobStep.objects.select_related('line_item').filter(machine__isnull=True):
        if (step.line_item.service_id, step.station_id) in by_hand_routes:
            step.by_hand = True
            step.save(update_fields=['by_hand'])
            count += 1
    print(f'  marked {count} step(s) by hand')


class Migration(migrations.Migration):

    dependencies = [
        ('jobs', '0040_job_step'),
        ('production', '0005_machine_max_width_mm'),
    ]

    operations = [
        migrations.AddField(
            model_name='jobstep',
            name='by_hand',
            field=models.BooleanField(
                default=False,
                help_text="Worked at the station's bench: the route names no machine type for this step.",
            ),
        ),
        migrations.AlterField(
            model_name='jobstep',
            name='machine',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.SET_NULL,
                related_name='job_steps',
                to='production.machine',
                help_text='Empty for work done by hand, or where nothing fitted and the coordinator must place it.',
            ),
        ),
        migrations.RunPython(mark_by_hand, migrations.RunPython.noop),
    ]
