# Generated by Django 4.0.4 on 2022-05-17 17:19

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('hermes', '0006_alter_message_author_alter_message_message_text'),
    ]

    operations = [
        migrations.AlterField(
            model_name='message',
            name='author',
            field=models.TextField(blank=True),
        ),
        migrations.AlterField(
            model_name='message',
            name='message_text',
            field=models.TextField(blank=True),
        ),
        migrations.AlterField(
            model_name='message',
            name='title',
            field=models.TextField(blank=True),
        ),
        migrations.AlterField(
            model_name='message',
            name='topic',
            field=models.TextField(blank=True),
        ),
    ]
