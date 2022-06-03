# Generated by Django 4.0.3 on 2022-03-30 19:11

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Message',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(blank=True, max_length=50)),
                ('author', models.CharField(blank=True, max_length=50)),
                ('data', models.JSONField()),
                ('message_text', models.TextField()),
            ],
        ),
    ]
