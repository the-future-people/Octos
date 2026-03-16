from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('jobs', '0003_jobstatuslog'),
    ]

    operations = [
        # ── Job model changes ────────────────────────────────────
        migrations.AddField(
            model_name='job',
            name='deposit_percentage',
            field=models.PositiveSmallIntegerField(
                choices=[(70, '70% Deposit'), (100, '100% (Full Payment)')],
                default=100,
                help_text='Percentage of estimated cost collected at payment',
            ),
        ),
        migrations.AddField(
            model_name='job',
            name='amount_paid',
            field=models.DecimalField(
                blank=True, null=True,
                max_digits=10, decimal_places=2,
                help_text='Actual amount paid by customer (set by cashier on confirmation)',
            ),
        ),
        # Update status field max_length to accommodate new status strings
        migrations.AlterField(
            model_name='job',
            name='status',
            field=models.CharField(
                max_length=30,
                choices=[
                    ('DRAFT', 'Draft'),
                    ('PENDING_PAYMENT', 'Pending Payment'),
                    ('PAID', 'Paid'),
                    ('CONFIRMED', 'Confirmed'),
                    ('IN_PROGRESS', 'In Progress'),
                    ('READY', 'Ready'),
                    ('OUT_FOR_DELIVERY', 'Out for Delivery'),
                    ('COMPLETE', 'Complete'),
                    ('CANCELLED', 'Cancelled'),
                    ('HALTED', 'Halted'),
                    ('SAMPLE_SENT', 'Sample Sent'),
                    ('REVISION_REQUESTED', 'Revision Requested'),
                    ('DESIGN_APPROVED', 'Design Approved'),
                    ('BRIEFED', 'Briefed (Deprecated)'),
                    ('DESIGN_IN_PROGRESS', 'Design In Progress (Deprecated)'),
                    ('QUEUED', 'Queued (Deprecated)'),
                    ('READY_FOR_PAYMENT', 'Ready for Payment (Deprecated)'),
                ],
                default='DRAFT',
            ),
        ),
        # ── Service model changes ─────────────────────────────────
        migrations.AddField(
            model_name='service',
            name='spec_template',
            field=models.JSONField(
                default=list,
                blank=True,
                help_text='Field definitions for the dynamic intake form.',
            ),
        ),
    ]