from hermes.models import Message, NonLocalizedEvent, NonLocalizedEventSequence, Target, Profile
from hermes.utils import extract_hop_auth
from hermes.brokers.hopskotch import get_user_writable_topics
from rest_framework import serializers
from astropy.coordinates import Longitude, Latitude
from astropy import units
from dateutil.parser import parse
from datetime import datetime
from django.utils.translation import gettext as _
import math

class ProfileSerializer(serializers.ModelSerializer):
    email = serializers.CharField(source='user.email', read_only=True)
    writable_topics = serializers.SerializerMethodField()

    class Meta:
        model = Profile
        fields = (
            'email', 'writable_topics'
        )

    def get_writable_topics(self, instance):
        request = self.context.get('request')
        hop_auth = extract_hop_auth(request)
        credential_name = hop_auth.username
        user_api_token = request.session['user_api_token']  # maintained in middleware

        return get_user_writable_topics(instance.user.username, credential_name, user_api_token, exclude_groups=['sys'])


class BaseTargetSerializer(serializers.ModelSerializer):
    right_ascension = serializers.SerializerMethodField()
    right_ascension_sexagesimal = serializers.SerializerMethodField()
    declination = serializers.SerializerMethodField()
    declination_sexagesimal = serializers.SerializerMethodField()

    class Meta:
        model = Target
        fields = [
            'id',
            'name',
            'right_ascension',
            'right_ascension_sexagesimal',
            'declination',
            'declination_sexagesimal',
        ]
    
    def get_right_ascension(self, obj):
        if obj.coordinate:
            return obj.coordinate.x

    def get_declination(self, obj):
        if obj.coordinate:
            return obj.coordinate.y

    def get_right_ascension_sexagesimal(self, obj):
        if obj.coordinate:
            a = Longitude(obj.coordinate.x, unit=units.degree)
            return a.to_string(unit=units.hour, sep=':')

    def get_declination_sexagesimal(self, obj):
        if obj.coordinate:
            a = Latitude(obj.coordinate.y, unit=units.degree)
            return a.to_string(unit=units.degree, sep=':')


class BaseMessageSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Message
        fields = [
            'id',
            'topic',
            'title',
            'submitter',
            'authors',
            'data',
            'message_text',
            'published',
            'message_parser',
            'created',
            'modified'
        ]


class BaseNonLocalizedEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = NonLocalizedEvent
        fields = [
            'event_id',
        ]


class MessageSerializer(BaseMessageSerializer):
    nonlocalizedevents = BaseNonLocalizedEventSerializer(many=True)
    targets = BaseTargetSerializer(many=True)

    class Meta(BaseMessageSerializer.Meta):
        fields = BaseMessageSerializer.Meta.fields + ['nonlocalizedevents', 'targets']


class NonLocalizedEventSequenceSerializer(serializers.ModelSerializer):
    message = BaseMessageSerializer()

    class Meta:
        model = NonLocalizedEventSequence
        fields = [
            'id',
            'sequence_number',
            'sequence_type',
            'message'
        ]


class NonLocalizedEventSerializer(BaseNonLocalizedEventSerializer):
    references = BaseMessageSerializer(many=True)
    sequences = serializers.SerializerMethodField()

    class Meta(BaseNonLocalizedEventSerializer.Meta):
        fields = BaseNonLocalizedEventSerializer.Meta.fields + ['sequences', 'references']

    def get_sequences(self, instance):
        sequences = instance.sequences.all().order_by('message__published')
        return NonLocalizedEventSequenceSerializer(sequences, many=True).data


class TargetSerializer(BaseTargetSerializer):
    messages = BaseMessageSerializer(many=True)

    class Meta(BaseTargetSerializer.Meta):
        fields = BaseTargetSerializer.Meta.fields + ['messages',]


def validate_date(date, date_format=None):
    if date_format:
        if 'jd' in date_format.lower():
            try:
                float(date)
            except ValueError:
                raise serializers.ValidationError({'date': _(f"Date: {date} does not parse. JD formatted dates must be a float value.")})
        else:
            try:
                datetime.strptime(date, date_format)
            except ValueError:
                raise serializers.ValidationError({'date': _(f"Date: {date} does not parse based on provided date format: {date_format}.")})
    else:
        try:
            parse(date)
        except ValueError:
            raise serializers.ValidationError({'date': _(f"Date: {date} does not parse with dateutil.parser.parse. Please specify a date_format or change your date.")})


class HermesMessageSerializer(serializers.Serializer):
    title = serializers.CharField(required=True)
    topic = serializers.CharField(required=True)
    message_text = serializers.CharField(required=False, default='', allow_blank=True)
    submitter = serializers.CharField(required=True)
    authors = serializers.CharField(required=False, default='', allow_blank=True)


class GenericHermesMessageSerializer(HermesMessageSerializer):
    data = serializers.JSONField(required=False)


class PhotometrySerializer(serializers.Serializer):
    target_name = serializers.CharField(required=True)
    ra = serializers.CharField(required=True)
    dec = serializers.CharField(required=True)
    date = serializers.CharField(required=True)
    date_format = serializers.CharField(required=False)
    telescope = serializers.CharField(required=False, default='', allow_blank=True)
    instrument = serializers.CharField(required=False, default='', allow_blank=True)
    band = serializers.CharField(required=True)
    brightness = serializers.FloatField(required=True)
    nondetection = serializers.BooleanField(required=False, default=False)
    brightness_error = serializers.FloatField(required=False)
    brightness_unit = serializers.ChoiceField(required=False, choices=["AB mag", "Vega mag", "mJy", "erg / s / cm² / Å"])

    def validate(self, data):
        validated_data = super().validate(data)
        validate_date(validated_data['date'], validated_data.get('date_format'))
        if not (validated_data.get('instrument') or validated_data.get('telescope')):
            error_msg = _("Must have at least one of telescope or instrument set")
            raise serializers.ValidationError({'telescope': error_msg, 'instrument': error_msg})
        return validated_data

    def validate_ra(self, value):
        try:
            float_ra = float(value)
            if not math.isfinite(float_ra):
                raise serializers.ValidationError(_("Value must be finite"))
            ra_angle = Longitude(float_ra * units.deg)
        except (ValueError, units.UnitsError, TypeError):
            try:
                ra_angle = Longitude(value, unit=units.hourangle)
            except:
                try:
                    ra_angle = Longitude(value)
                except:
                    raise serializers.ValidationError(_("Must be in a format astropy understands"))
        return ra_angle.deg

    def validate_dec(self, value):
        try:
            float_dec = float(value)
            if not math.isfinite(float_dec):
                raise serializers.ValidationError(_("Dec value must be finite"))
            dec_angle = Latitude(float_dec * units.deg)
        except (ValueError, units.UnitsError, TypeError):
            try:
                dec_angle = Latitude(value, unit=units.hourangle)
            except:
                try:
                    dec_angle = Latitude(value)
                except:
                    raise serializers.ValidationError(_("Must be in a format astropy understands"))
        return dec_angle.deg


class PhotometryDataSerializer(serializers.Serializer):
    event_id = serializers.CharField(required=False)
    extra_data = serializers.JSONField(required=False)
    photometry = PhotometrySerializer(many=True)

    def validate_photometry(self, value):
        if len(value) < 1:
            raise serializers.ValidationError(_('At least one piece of photometry must be defined'))
        return value


class HermesPhotometrySerializer(HermesMessageSerializer):
    data = PhotometryDataSerializer()


class DiscoveryDataSerializer(PhotometryDataSerializer):
    # TODO: Set up choices, maybe from the fink portal classes
    type = serializers.CharField(required=False, default='', allow_blank=True)


class HermesDiscoverySerializer(HermesMessageSerializer):
    data = DiscoveryDataSerializer()
