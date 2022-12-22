from hermes.models import Message, NonLocalizedEvent, NonLocalizedEventSequence, Target
from rest_framework import serializers
from astropy.coordinates import Longitude, Latitude
from astropy import units
from dateutil.parser import parse
from datetime import datetime
from django.utils.translation import gettext as _


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
    message_text = serializers.CharField(required=True)
    submitter = serializers.CharField(required=True)
    authors = serializers.CharField(required=False, default='')


class GenericHermesMessageSerializer(HermesMessageSerializer):
    data = serializers.JSONField(required=False)


class CandidateSerializer(serializers.Serializer):
    target_name = serializers.CharField(required=True)
    ra = serializers.CharField(required=True)
    dec = serializers.CharField(required=True)
    date = serializers.CharField(required=True)
    date_format = serializers.CharField(required=False)
    telescope = serializers.CharField(required=False)
    instrument = serializers.CharField(required=False)
    band = serializers.CharField(required=True)
    brightness = serializers.FloatField(required=False)
    brightness_error = serializers.FloatField(required=False)
    brightness_unit = serializers.ChoiceField(required=False, choices=["AB mag", "Vega mag", "mJy", "erg / s / cm² / Å"])

    def validate(self, data):
        validated_data = super().validate(data)
        validate_date(validated_data['date'], validated_data.get('date_format'))
        return validated_data

    def validate_ra(self, value):
        try:
            float_ra = float(value)
            ra_angle = Longitude(float_ra * units.deg)
        except:
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
            dec_angle = Latitude(float_dec * units.deg)
        except:
            try:
                dec_angle = Latitude(value, unit=units.hourangle)
            except:
                try:
                    dec_angle = Latitude(value)
                except:
                    raise serializers.ValidationError(_("Must be in a format astropy understands"))
        return dec_angle.deg


class CandidateDataSerializer(serializers.Serializer):
    event_id = serializers.CharField(required=True)
    extra_data = serializers.JSONField(required=False)
    candidates = CandidateSerializer(many=True, required=True)

    def validate_candidates(self, value):
        if len(value) < 1:
            raise serializers.ValidationError(_('At least one candidate must be defined'))
        return value


class HermesCandidateSerializer(HermesMessageSerializer):
    data = CandidateDataSerializer()


#TODO: Right now the Photometry and Candidate serializers are the same, but I expect they will become different later
class PhotometrySerializer(serializers.Serializer):
    target_name = serializers.CharField(required=True)
    ra = serializers.CharField(required=True)
    dec = serializers.CharField(required=True)
    date = serializers.CharField(required=True)
    date_format = serializers.CharField(required=False)
    telescope = serializers.CharField(required=False)
    instrument = serializers.CharField(required=False)
    band = serializers.CharField(required=True)
    brightness = serializers.FloatField(required=False)
    brightness_error = serializers.FloatField(required=False)
    brightness_unit = serializers.ChoiceField(required=False, choices=["AB mag", "Vega mag", "mJy", "erg / s / cm² / Å"])

    def validate(self, data):
        validated_data = super().validate(data)
        validate_date(validated_data['date'], validated_data.get('date_format'))
        return validated_data

    def validate_ra(self, value):
        try:
            float_ra = float(value)
            ra_angle = Longitude(float_ra * units.deg)
        except:
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
            dec_angle = Latitude(float_dec * units.deg)
        except:
            try:
                dec_angle = Latitude(value, unit=units.hourangle)
            except:
                try:
                    dec_angle = Latitude(value)
                except:
                    raise serializers.ValidationError(_("Must be in a format astropy understands"))
        return dec_angle.deg


class PhotometryDataSerializer(serializers.Serializer):
    event_id = serializers.CharField(required=True)
    extra_data = serializers.JSONField(required=False)
    photometry = PhotometrySerializer(many=True)

    def validate_photometry(self, value):
        if len(value) < 1:
            raise serializers.ValidationError(_('At least one piece of photometry must be defined'))
        return value

class HermesPhotometrySerializer(HermesMessageSerializer):
    data = PhotometryDataSerializer()
