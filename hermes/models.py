import uuid
import logging
from pydoc_data.topics import topics
from django.db import models
from django.utils import timezone
from django.contrib.gis.db import models as gis_models
from django.contrib.auth.models import User
from django.contrib.postgres.fields import ArrayField
from rest_framework.authtoken.models import Token
from hermes.brokers.hopskotch import get_user_writable_topics, get_user_api_token, get_user_groups

logger = logging.getLogger(__name__)


class Profile(models.Model):
    # This model will be used to store user settings, such as topic sort/filter preferences
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    credential_name = models.CharField(max_length=256, blank=True, default='', help_text='Scimma Auth User Scram Credential name')
    credential_password = models.CharField(max_length=256, blank=True, default='', help_text='Scimma Auth User Scram Credential password')

    tns_bot_id = models.BigIntegerField(default=-1, blank=True, help_text='TNS Bot ID to use when submitting to TNS from this user')
    tns_bot_name = models.CharField(max_length=64, default='', blank=True,
                                    help_text='TNS Bot Name to use when submitting to TNS from this user')
    tns_bot_api_token = models.CharField(max_length=64, default='', blank=True,
                                         help_text='TNS Bot API Token to use when submitting to TNS from this user')

    @property
    def api_token(self):
        return Token.objects.get_or_create(user=self.user)[0]

    @property
    def writable_topics(self):
        try:
            user_api_token = get_user_api_token(self.user.username)
        except Exception as e:
            logger.warning(f"Failed to retrieve user api token: {repr(e)}")
            return []
        return get_user_writable_topics(self.user.username, self.credential_name, user_api_token, exclude_groups=['sys'])

    @property
    def group_memberships(self):
        """ Returns a dictionary of the form {group: group_permission} for all user's group memberships
        """
        try:
            user_api_token = get_user_api_token(self.user.username)
        except Exception as e:
            logger.warning(f"Failed to retrieve user api token: {repr(e)}")
            return {}
        return {group['group']: group['status'] for group in get_user_groups(self.user.username, user_api_token)}


class OAuthToken(models.Model):
    class IntegratedApps(models.TextChoices):
        GCN = 'GCN', 'GCN'

    integrated_app = models.CharField(max_length=32, choices=IntegratedApps.choices, default=IntegratedApps.GCN)
    token_type = models.CharField(max_length=40)
    access_token=models.CharField(max_length=2048)
    refresh_token=models.CharField(max_length=2048)
    expires_at=models.DateTimeField(null=True)
    expires_in = models.PositiveIntegerField(null=True, blank=True)
    group_permissions = ArrayField(models.CharField(max_length=255, blank=True), default=list, blank=True,
                                          help_text='List of permissions associated with this token')
    user = models.ForeignKey(User, on_delete=models.CASCADE, default=1)

    def is_expired(self):
        return self.expires_at <= timezone.now()

    def to_token(self):
        return dict(
            access_token=self.access_token,
            token_type=self.token_type,
            refresh_token=self.refresh_token,
            expires_at=self.expires_at,
            expires_in=self.expires_in,
        )


class Message(models.Model):
    class Meta:
        # -created means newest first
        ordering = ['-id']  # to avoid DRF pagination UnorderedObjectListWarning

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)

    def __str__(self):
        return f'{self.uuid}'


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
    data = models.JSONField(null=True, blank=True)
    sequence_number = models.PositiveSmallIntegerField(
        default=1,
        help_text='The sequence_number or iteration of a specific nonlocalized event.'    
    )
    sequence_type = models.CharField(max_length=64, default='', blank=True, choices=NonLocalizedEventSequenceType.choices, help_text='The alert type for this sequence')
    created = models.DateTimeField(auto_now_add=True, verbose_name='Time Created')
