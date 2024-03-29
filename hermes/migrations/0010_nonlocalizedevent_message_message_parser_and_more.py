# Generated by Django 4.1.3 on 2022-11-28 23:05

import django.contrib.gis.db.models.fields
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('hermes', '0009_alter_message_published'),
    ]

    operations = [
        migrations.CreateModel(
            name='NonLocalizedEvent',
            fields=[
                ('event_id', models.CharField(db_index=True, default='', help_text='The GraceDB event id. Sometimes reffered to as TRIGGER_NUM in LVC notices.', max_length=64, primary_key=True, serialize=False)),
            ],
        ),
        migrations.AddField(
            model_name='message',
            name='message_parser',
            field=models.CharField(default='', max_length=128),
        ),
        migrations.AlterField(
            model_name='message',
            name='published',
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now, verbose_name='Time Published to Stream from message metadata.'),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='message',
            name='topic',
            field=models.TextField(blank=True, db_index=True),
        ),
        migrations.CreateModel(
            name='Target',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(db_index=True, max_length=128)),
                ('coordinate', django.contrib.gis.db.models.fields.PointField(blank=True, null=True, srid=4326)),
                ('messages', models.ManyToManyField(related_name='targets', to='hermes.message')),
            ],
        ),
        migrations.CreateModel(
            name='NonLocalizedEventSequence',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('sequence_number', models.PositiveSmallIntegerField(default=1, help_text='The sequence_number or iteration of a specific nonlocalized event.')),
                ('sequence_type', models.CharField(blank=True, choices=[('EARLY_WARNING', 'EARLY_WARNING'), ('RETRACTION', 'RETRACTION'), ('PRELIMINARY', 'PRELIMINARY'), ('INITIAL', 'INITIAL'), ('UPDATE', 'UPDATE')], default='', help_text='The alert type for this sequence', max_length=64)),
                ('event', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='sequences', to='hermes.nonlocalizedevent')),
                ('message', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='sequences', to='hermes.message')),
            ],
        ),
        migrations.AddField(
            model_name='nonlocalizedevent',
            name='references',
            field=models.ManyToManyField(related_name='nonlocalizedevents', to='hermes.message'),
        ),
    ]
