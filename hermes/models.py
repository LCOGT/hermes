import uuid
from pydoc_data.topics import topics
from django.db import models
from django.contrib.gis.db import models as gis_models
from django.contrib.auth.models import User
from rest_framework.authtoken.models import Token
from hermes.brokers.hopskotch import get_user_writable_topics, get_user_api_token


class Profile(models.Model):
    # This model will be used to store user settings, such as topic sort/filter preferences
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    hop_user_pk = models.BigIntegerField(default=-1, help_text='Scimma Auth User primary key')
    credential_pk = models.BigIntegerField(default=-1, help_text='Scimma Auth User Scram Credential primary key')
    credential_name = models.CharField(max_length=256, blank=True, default='', help_text='Scimma Auth User Scram Credential name')
    credential_password = models.CharField(max_length=256, blank=True, default='', help_text='Scimma Auth User Scram Credential password')

    @property
    def api_token(self):
        return Token.objects.get_or_create(user=self.user)[0]

    @property
    def writable_topics(self):
        user_api_token = get_user_api_token(self.user.username)
        return get_user_writable_topics(self.user.username, self.hop_user_pk, self.credential_name, self.credential_pk, user_api_token, exclude_groups=['sys'])


class Message(models.Model):
    class Meta:
        # -created means newest first
        ordering = ['-created']  # to avoid DRF pagination UnorderedObjectListWarning

    topic = models.TextField(blank=True, db_index=True)
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)
    title = models.TextField(blank=True)
    submitter = models.TextField(blank=True)
    authors = models.TextField(blank=True)
    data = models.JSONField(null=True, blank=True)
    message_text = models.TextField(blank=True)
    published = models.DateTimeField(auto_now_add=True,
                                     verbose_name='Time Published to Stream from message metadata.')
    message_parser = models.CharField(max_length=128, default='', blank=True)
    created = models.DateTimeField(auto_now_add=True, verbose_name='Time Created')
    modified = models.DateTimeField(auto_now=True, verbose_name='Last Modified')

    def __str__(self):
        return f'{self.uuid} on {self.topic}: {self.title} from {self.authors}'


class Target(models.Model):
    name = models.CharField(max_length=128, db_index=True)
    messages = models.ManyToManyField(Message, related_name='targets')
    coordinate = gis_models.PointField(null=True, blank=True)


class NonLocalizedEvent(models.Model):
    class NonLocalizedEventType(models.TextChoices):
        GRAVITATIONAL_WAVE = 'GW', 'Gravitational Wave'
        GAMMA_RAY_BURST = 'GRB', 'Gamma-ray Burst'
        NEUTRINO = 'NU', 'Neutrino'
        UNKNOWN = 'UNK', 'Unknown'

    event_id = models.CharField(
        max_length=64,
        default='',
        primary_key=True,
        db_index=True,
        help_text='The GraceDB event id for GW events, sometimes reffered to as TRIGGER_NUM in LVC notices. Or the Icecube runnum_eventnum for NU events'
    )
    event_type = models.CharField(
        max_length=32,
        choices=NonLocalizedEventType.choices,
        default=NonLocalizedEventType.GRAVITATIONAL_WAVE,
        help_text='The type of NonLocalizedEvent'
    )
    references = models.ManyToManyField(Message, related_name='nonlocalizedevents')


class NonLocalizedEventSequence(models.Model):
    class NonLocalizedEventSequenceType(models.TextChoices):
        EARLY_WARNING = 'EARLY_WARNING', 'EARLY_WARNING'
        RETRACTION = 'RETRACTION', 'RETRACTION'
        PRELIMINARY = 'PRELIMINARY', 'PRELIMINARY'
        INITIAL = 'INITIAL', 'INITIAL'
        UPDATE = 'UPDATE', 'UPDATE'

    message = models.ForeignKey(Message, related_name='sequences', on_delete=models.CASCADE)
    event = models.ForeignKey(NonLocalizedEvent, related_name='sequences', on_delete=models.CASCADE)
    sequence_number = models.PositiveSmallIntegerField(
        default=1,
        help_text='The sequence_number or iteration of a specific nonlocalized event.'    
    )
    skymap_version = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text='Version of the skymap for this event, derived from detecting a change in the raw skymap from its hash'
    )
    skymap_hash = models.UUIDField(
        null=True, blank=True,
        help_text='A UUID from an md5 hash of the raw skymap file contents, used to detect when the skymap has changed'
    )
    combined_skymap_version = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text='Version of the combined skymap for this event, derived from detecting a change in the raw skymap from its hash'
    )
    combined_skymap_hash = models.UUIDField(
        null=True, blank=True,
        help_text='A UUID from an md5 hash of the raw combined skymap file contents, used to detect when the skymap has changed'
    )
    sequence_type = models.CharField(max_length=64, default='', blank=True, choices=NonLocalizedEventSequenceType.choices, help_text='The alert type for this sequence')
