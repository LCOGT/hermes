# Generated by Django 4.1.5 on 2023-01-24 22:19

from django.db import migrations, models
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('hermes', '0012_profile'),
    ]

    operations = [
        # create the intermediary null field and defer creating the unique constraint until
        # we’ve populated unique values on all the rows in next migration ('0014_populate_uuid_values')
        migrations.AddField(
            model_name='message',
            name='uuid',
            field=models.UUIDField(default=uuid.uuid4, null=True),
        ),
    ]