from pydoc_data.topics import topics
from django.db import models
from django.db.models.fields.json import KeyTransform
from django.contrib.gis.db import models as gis_models


class Message(models.Model):
    class Meta:
        # -created means newest first
        ordering = ['-created']  # to avoid DRF pagination UnorderedObjectListWarning

    topic = models.TextField(blank=True, db_index=True)
    title = models.TextField(blank=True)
    author = models.TextField(blank=True)
    data = models.JSONField(null=True)
    message_text = models.TextField(blank=True)
    published = models.DateTimeField(auto_now_add=True,
                                     verbose_name='Time Published to Stream from message metadata.')

    message_parser = models.CharField(max_length=128, default='')
    created = models.DateTimeField(auto_now_add=True, verbose_name='Time Created')
    modified = models.DateTimeField(auto_now=True, verbose_name='Last Modified')

    def __str__(self):
        return f'{self.topic}: {self.title} from {self.author}'


class Target(models.Model):
    name = models.CharField(max_length=128, db_index=True)
    messages = models.ManyToManyField(Message, related_name='targets')
    coordinate = gis_models.PointField(null=True, blank=True)


class NonLocalizedEvent(models.Model):
    event_id = models.CharField(
        max_length=64,
        default='',
        primary_key=True,
        db_index=True,
        help_text='The GraceDB event id. Sometimes reffered to as TRIGGER_NUM in LVC notices.'
    )
    references = models.ManyToManyField(Message, related_name='nonlocalizedevents')


class NonLocalizedEventSequence(models.Model):
    SEQUENCE_TYPES = (
        ('EARLY_WARNING', 'EARLY_WARNING'),
        ('RETRACTION', 'RETRACTION'),
        ('PRELIMINARY', 'PRELIMINARY'),
        ('INITIAL', 'INITIAL'),
        ('UPDATE', 'UPDATE')
    )
    message = models.ForeignKey(Message, related_name='sequences', on_delete=models.CASCADE)
    event = models.ForeignKey(NonLocalizedEvent, related_name='sequences', on_delete=models.CASCADE)
    sequence_number = models.PositiveSmallIntegerField(
        default=1,
        help_text='The sequence_number or iteration of a specific nonlocalized event.'    
    )
    sequence_type = models.CharField(max_length=64, default='', blank=True, choices=SEQUENCE_TYPES, help_text='The alert type for this sequence')
