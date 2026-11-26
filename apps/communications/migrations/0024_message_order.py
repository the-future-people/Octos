import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('communications', '0023_customer_files'),
        ('storefront', '0021_pay_at_counter'),
    ]

    operations = [
        migrations.AddField(
            model_name='message',
            name='order',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name='chat_messages', to='storefront.onlineorder'),
        ),
    ]
