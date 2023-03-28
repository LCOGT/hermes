# Generated by Django 4.1.5 on 2023-01-24 22:28

import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('hermes', '0014_populate_uuid_values'),
    ]

    operations = [
        migrations.AlterField(
            model_name='message',
            name='uuid',
            field=models.UUIDField(default=uuid.uuid4, unique=True),
        ),

    ]
