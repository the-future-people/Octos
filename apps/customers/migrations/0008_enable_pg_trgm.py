# apps/customers/migrations/0008_enable_pg_trgm.py
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('customers', '0007_customerprofile_total_spend_and_more'),
    ]

    operations = [
        migrations.RunSQL(
            sql     = 'CREATE EXTENSION IF NOT EXISTS pg_trgm;',
            reverse_sql = 'DROP EXTENSION IF EXISTS pg_trgm;',
        ),
    ]