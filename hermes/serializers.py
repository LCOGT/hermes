from hermes.models import Message, NonLocalizedEvent, NonLocalizedEventSequence, Target
from rest_framework import serializers
from astropy.coordinates import Angle, SkyCoord
from astropy import units
from dateutil.parser import parse
from datetime import datetime

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
            a = Angle(obj.coordinate.x, unit=units.degree)
            return a.to_string(unit=units.hour, sep=':')

    def get_declination_sexagesimal(self, obj):
        if obj.coordinate:
            a = Angle(obj.coordinate.y, unit=units.degree)
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


def validate_coordinates(ra, dec):
    try:
        # First see if the coordinates are simple float values
        float_ra, float_dec = float(ra), float(dec)
        SkyCoord(float_ra, float_dec, unit=(units.deg, units.deg))
        return float_ra, float_dec
    except Exception:
        try:
            coord = SkyCoord(ra, dec, unit=(units.hourangle, units.deg))
            return coord.ra.deg, coord.dec.deg
        except Exception as ex:
            raise serializers.ValidationError("Failed to validate coordinates. Please submit ra/dec in either deg/deg or ha/deg formats")


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
        validated_data['ra'], validated_data['dec'] = validate_coordinates(validated_data['ra'], validated_data['dec'])

        date_format = validated_data.get('date_format')
        if date_format:
            if 'jd' in date_format.lower():
                try:
                    float(validated_data['date'])
                except ValueError:
                    raise serializers.ValidationError(f"Date: {validated_data['date']} does not parse. JD formatted dates must be a float value.")
            else:
                try:
                    datetime.strptime(validated_data['date'], date_format)
                except ValueError:
                    raise serializers.ValidationError(f"Date: {validated_data['date']} does not parse based on provided date format: {date_format}.")
        else:
            try:
                parse(validated_data['date'])
            except ValueError:
                raise serializers.ValidationError(f"Date: {validated_data['date']} does not parse with dateutil.parser.parse. Please specify a date_format or change your date.")
        return validated_data


class CandidateDataSerializer(serializers.Serializer):
    event_id = serializers.CharField(required=True)
    extra_data = serializers.JSONField(required=False)
    candidates = CandidateSerializer(many=True)


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
        validated_data['ra'], validated_data['dec'] = validate_coordinates(validated_data['ra'], validated_data['dec'])

        date_format = validated_data.get('date_format')
        if date_format:
            if 'jd' in date_format.lower():
                try:
                    float(validated_data['date'])
                except ValueError:
                    raise serializers.ValidationError(f"Date: {validated_data['date']} does not parse. JD formatted dates must be a float value.")
            else:
                try:
                    datetime.strptime(validated_data['date'], validated_data['date'])
                except ValueError:
                    raise serializers.ValidationError(f"Date: {validated_data['date']} does not parse based on provided date format: {date_format}.")
        else:
            try:
                parse(validated_data['date'])
            except ValueError:
                raise serializers.ValidationError(f"Date: {validated_data['date']} does not parse with dateutil.parser.parse. Please specify a date_format or change your date.")
        return validated_data


class PhotometryDataSerializer(serializers.Serializer):
    event_id = serializers.CharField(required=True)
    extra_data = serializers.JSONField(required=False)
    candidates = CandidateSerializer(many=True)


class HermesPhotometrySerializer(HermesMessageSerializer):
    data = PhotometryDataSerializer()
