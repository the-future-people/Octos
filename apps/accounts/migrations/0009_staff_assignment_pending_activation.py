import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0008_customuser_employment_status'),
        ('hr', '0005_alter_stagequestionnaire_options_and_more'),
        ('organization', '0003_branch_closing_time_branch_getfund_rate_and_more'),
    ]

    operations = [

        # ── StaffAssignment ──────────────────────────────────
        migrations.CreateModel(
            name='StaffAssignment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('designation', models.CharField(
                    choices=[('MAIN', 'Main'), ('DEPUTY', 'Deputy'), ('MEMBER', 'Member')],
                    default='MEMBER',
                    max_length=10,
                )),
                ('effective_from', models.DateField()),
                ('effective_until', models.DateField(
                    blank=True, null=True,
                    help_text='Null means this is the current active assignment.',
                )),
                ('is_current', models.BooleanField(default=True, db_index=True)),
                ('ended_reason', models.CharField(
                    blank=True, null=True,
                    choices=[
                        ('PROMOTION',   'Promotion'),
                        ('REPLACEMENT', 'Replacement'),
                        ('RESIGNATION', 'Resignation'),
                        ('TRANSFER',    'Transfer'),
                        ('DEMOTION',    'Demotion'),
                        ('ACTIVATION',  'Activation'),
                    ],
                    max_length=20,
                )),
                ('branch', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='staff_assignments',
                    to='organization.branch',
                )),
                ('region', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='staff_assignments',
                    to='organization.region',
                )),
                ('role', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='assignments',
                    to='accounts.role',
                )),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='assignments',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('ended_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='assignments_closed',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'ordering': ['-effective_from'],
            },
        ),

        migrations.AddConstraint(
            model_name='staffassignment',
            constraint=models.UniqueConstraint(
                fields=['role', 'branch', 'designation'],
                condition=Q(is_current=True, designation='MAIN', branch__isnull=False),
                name='unique_main_per_role_per_branch',
            ),
        ),
        migrations.AddConstraint(
            model_name='staffassignment',
            constraint=models.UniqueConstraint(
                fields=['role', 'branch', 'designation'],
                condition=Q(is_current=True, designation='DEPUTY', branch__isnull=False),
                name='unique_deputy_per_role_per_branch',
            ),
        ),
        migrations.AddConstraint(
            model_name='staffassignment',
            constraint=models.UniqueConstraint(
                fields=['role', 'region', 'designation'],
                condition=Q(is_current=True, designation='MAIN', region__isnull=False),
                name='unique_main_per_role_per_region',
            ),
        ),
        migrations.AddConstraint(
            model_name='staffassignment',
            constraint=models.UniqueConstraint(
                fields=['role', 'region', 'designation'],
                condition=Q(is_current=True, designation='DEPUTY', region__isnull=False),
                name='unique_deputy_per_role_per_region',
            ),
        ),

        # ── PendingActivation ────────────────────────────────
        migrations.CreateModel(
            name='PendingActivation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('designation', models.CharField(
                    choices=[('MAIN', 'Main'), ('DEPUTY', 'Deputy'), ('MEMBER', 'Member')],
                    default='MAIN',
                    max_length=10,
                )),
                ('start_date', models.DateField()),
                ('shadow_days', models.IntegerField(
                    default=7,
                    help_text='Number of days of read-only shadow access before start_date.',
                )),
                ('conflict_resolution', models.CharField(
                    blank=True, null=True,
                    choices=[
                        ('DEACTIVATE',  'Deactivate'),
                        ('REASSIGN',    'Reassign to another branch'),
                        ('ROLE_CHANGE', 'Change role'),
                    ],
                    max_length=20,
                )),
                ('conflict_new_designation', models.CharField(
                    blank=True, null=True,
                    choices=[('MAIN', 'Main'), ('DEPUTY', 'Deputy'), ('MEMBER', 'Member')],
                    max_length=10,
                )),
                ('generated_email',    models.CharField(max_length=255, blank=True)),
                ('generated_username', models.CharField(max_length=100, blank=True)),
                ('temp_password_hash', models.CharField(max_length=255, blank=True)),
                ('status', models.CharField(
                    choices=[
                        ('PENDING',   'Pending'),
                        ('SHADOW',    'Shadow period active'),
                        ('ACTIVATED', 'Activated'),
                        ('CANCELLED', 'Cancelled'),
                    ],
                    default='PENDING',
                    max_length=10,
                )),
                ('activated_at', models.DateTimeField(blank=True, null=True)),
                ('cancelled_at', models.DateTimeField(blank=True, null=True)),
                ('user', models.OneToOneField(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='pending_activation',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('applicant', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='activation',
                    to='hr.applicant',
                )),
                ('role', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='pending_activations',
                    to='accounts.role',
                )),
                ('branch', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='pending_activations',
                    to='organization.branch',
                )),
                ('region', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='pending_activations',
                    to='organization.region',
                )),
                ('conflict_user', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='displaced_by_activation',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('conflict_new_branch', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='conflict_reassignments',
                    to='organization.branch',
                )),
                ('conflict_new_role', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='conflict_role_changes',
                    to='accounts.role',
                )),
                ('created_by', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='activations_created',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('cancelled_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='activations_cancelled',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'ordering': ['start_date'],
            },
        ),
    ]