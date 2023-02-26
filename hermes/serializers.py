from hermes.models import Message, NonLocalizedEvent, NonLocalizedEventSequence, Target, Profile
from hermes.utils import extract_hop_auth, TNS_TYPES
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
            'uuid',
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


class ReferenceMessageSerializer(BaseMessageSerializer):
    targets = BaseTargetSerializer(many=True)

    class Meta(BaseMessageSerializer.Meta):
        fields = BaseMessageSerializer.Meta.fields + ['targets']


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
    references = ReferenceMessageSerializer(many=True)
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


def validate_date(date):
    try:
        float(date)
    except ValueError:
        try:
            parse(date)
        except ValueError:
            raise serializers.ValidationError({'date': _(f"Date: {date} does not parse with dateutil.parser.parse. Please specify the date in a standard format or as a JD.")})


class ReferenceDataSerializer(serializers.Serializer):
    source = serializers.CharField(required=False)
    citation = serializers.CharField(required=False)
    url = serializers.URLField(required=False)

    def validate(self, data):
        validated_data = super().validate(data)
        if not (validated_data.get('source') and validated_data.get('citation')):
            if validated_data.get('source'):
                raise serializers.ValidationError({
                    'citation': 'Must set citation with source'
                })
            if validated_data.get('citation'):
                raise serializers.ValidationError({
                    'source': 'Must set source with citation'
                })
            if not validated_data.get('url'):
                raise serializers.ValidationError({
                    'source': 'Must set source/citation or url',
                    'citation': 'Must set source/citation or url',
                    'url': 'Must set source/citation or url',
                })
        return validated_data

class OrbitalElementsSerializer(serializers.Serializer):
    epoch_of_elements = serializers.CharField(required=True)
    orbinc = serializers.FloatField(required=True)
    longascnode = serializers.FloatField(required=True)
    argofperih = serializers.FloatField(required=True)
    eccentricity = serializers.FloatField(required=True)
    meandist = serializers.FloatField(required=False)
    meananom = serializers.FloatField(required=False)
    perihdist = serializers.FloatField(required=False)
    epochofperih = serializers.FloatField(required=False)

    def validate(self, data):
        validated_data = super().validate(data)
        if not ((validated_data.get('meandist') and validated_data.get('meananom')) or (
            validated_data.get('perihdist') and validated_data.get('epochofperih'))):
            if validated_data.get('meandist'):
                raise serializers.ValidationError({
                    'meananom': 'Must set meananom when meandist is set'
                })
            if validated_data.get('meananom'):
                raise serializers.ValidationError({
                    'meandist': 'Must set meandist when meananom is set'
                })
            if validated_data.get('perihdist'):
                raise serializers.ValidationError({
                    'epochofperih': 'Must set epochofperih when perihdist is set'
                })
            if validated_data.get('epochofperih'):
                raise serializers.ValidationError({
                    'perihdist': 'Must set perihdist when epochofperih is set'
                })
            raise serializers.ValidationError({
                'meananom': "Must set meananom/meandist or epochofperih/perihdist",
                'meandist': "Must set meananom/meandist or epochofperih/perihdist",
                'epochofperih': "Must set meananom/meandist or epochofperih/perihdist",
                'perihdist': "Must set meananom/meandist or epochofperih/perihdist",
            })

        return validated_data


class DiscoveryInfoSerializer(serializers.Serializer):
    reporting_group = serializers.CharField(required=False)
    discovery_source = serializers.CharField(required=False)
    transient_type = serializers.ChoiceField(required=False, choices=['PSN', 'nuc', 'PNV', 'AGN', 'Other'])
    proprietary_period = serializers.FloatField(required=False)
    proprietary_period_units = serializers.ChoiceField(required=False, default='Days', choices=['Seconds', 'Days', 'Years'])


class TargetDataSerializer(serializers.Serializer):
    name = serializers.CharField(required=True)
    ra = serializers.CharField(required=False)
    dec = serializers.CharField(required=False)
    ra_error = serializers.FloatField(required=False)
    dec_error = serializers.FloatField(required=False)
    ra_error_units = serializers.ChoiceField(required=False, default='degrees', choices=[
        'degrees', 'marcsec', 'arcsec', 'arcmin'
    ])
    dec_error_units = serializers.ChoiceField(required=False, default='degrees', choices=[
        'degrees', 'marcsec', 'arcsec', 'arcmin'
    ])
    pm_ra = serializers.FloatField(required=False)
    pm_dec = serializers.FloatField(required=False)
    epoch = serializers.CharField(required=False, default='J2000')
    orbital_elements = OrbitalElementsSerializer(required=False)
    discovery_info = DiscoveryInfoSerializer(required=False)
    redshift = serializers.FloatField(required=False)
    host_name = serializers.CharField(required=False)
    host_redshift = serializers.FloatField(required=False)
    aliases = serializers.ListField(child=serializers.CharField(), required=False)
    group_associations = serializers.CharField(required=False)

    def validate(self, data):
        validated_data = super().validate(data)
        if not (validated_data.get('ra') and validated_data.get('dec')):
            if validated_data.get('ra'):
                raise serializers.ValidationError({
                    'dec': 'Must set dec if ra is set'
                })
            elif validated_data.get('dec'):
                raise serializers.ValidationError({
                    'ra': 'Must set ra if dec is set'
                })
            if not validated_data.get('orbital_elements'):
                raise serializers.ValidationError({
                    'ra': 'ra/dec or orbital elements are required',
                    'dec': 'ra/dec or orbital elements are required',
                    'orbital_elements': 'ra/dec or orbital elements are required'
                })

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

class CommonDataSerializer(serializers.Serializer):
    target_name = serializers.CharField(required=True)
    date_obs = serializers.CharField(required=False)
    telescope = serializers.CharField(required=False, default='', allow_blank=True)
    instrument = serializers.CharField(required=False, default='', allow_blank=True)

    def validate(self, data):
        validated_data = super().validate(data)
        validate_date(validated_data['date_obs'])
        if not (validated_data.get('instrument') or validated_data.get('telescope')):
            error_msg = _("Must have at least one of telescope or instrument set")
            raise serializers.ValidationError({'telescope': error_msg, 'instrument': error_msg})
        return validated_data


class PhotometryDataSerializer(CommonDataSerializer):
    bandpass = serializers.CharField(required=True)
    brightness = serializers.FloatField(required=False)
    brightness_error = serializers.FloatField(required=False)
    brightness_unit = serializers.ChoiceField(required=False, default="AB mag", choices=["AB mag", "Vega mag", "mJy", "erg / s / cm² / Å"])
    new_discovery = serializers.BooleanField(default=False, required=False)
    exposure_time = serializers.FloatField(required=False)
    observer = serializers.CharField(required=False)
    comments = serializers.CharField(required=False)
    limiting_brightness = serializers.FloatField(required=False)
    limiting_brightness_unit = serializers.ChoiceField(required=False, default="AB mag", choices=["AB mag", "Vega mag", "mJy", "erg / s / cm² / Å"])
    group_associations = serializers.CharField(required=False)

    def validate(self, data):
        validated_data = super().validate(data)
        if not (validated_data.get('brightness') or validated_data.get('limiting_brightness')):
            raise serializers.ValidationError({
                'brightness': 'brightness or limiting_brightness are required',
                'limiting_brightness': 'brightness or limiting_brightness are required'
            })

        return validated_data


class FluxDataSerializer(serializers.Serializer):
    value = serializers.FloatField(required=True)
    error = serializers.FloatField(required=False)
    unit = serializers.ChoiceField(required=False, default="mJy", choices=["mJy", "erg / s / cm² / Å"])
    wavelength = serializers.FloatField(required=True)
    wavelength_unit = serializers.ChoiceField(required=False, choices=['Å', 'nm'])


class SpectroscopyDataSerialzier(CommonDataSerializer):
    setup = serializers.CharField(required=False)
    exposure_time = serializers.FloatField(required=False)
    flux = FluxDataSerializer(many=True, required=True)
    classification = serializers.ChoiceField(required=False, default=TNS_TYPES[-1], choices=TNS_TYPES)
    proprietary_period = serializers.FloatField(required=False)
    proprietary_period_units = serializers.ChoiceField(required=False, default='Days', choices=['Seconds', 'Days', 'Years'])
    comments = serializers.CharField(required=False)
    group_associations = serializers.CharField(required=False)
    observer = serializers.CharField(required=False)
    reducer = serializers.CharField(required=False)
    spec_type = serializers.ChoiceField(required=False, choices=['Object', 'Host', 'Synthetic', 'Sky', 'Arcs'])


class AstrometryDataSerializer(CommonDataSerializer):
    ra = serializers.CharField(required=True)
    dec = serializers.CharField(required=True)
    ra_error = serializers.FloatField(required=False)
    dec_error = serializers.FloatField(required=False)
    ra_error_units = serializers.ChoiceField(required=False, default='degrees', choices=[
        'degrees', 'arcsec', 'arcmin'
    ])
    dec_error_units = serializers.ChoiceField(required=False, default='degrees', choices=[
        'degrees', 'arcsec', 'arcmin'
    ])
    mpc_sitecode = serializers.CharField(required=False)
    brightness = serializers.FloatField(required=False)
    brightness_error = serializers.FloatField(required=False)
    brightness_unit = serializers.ChoiceField(required=False, default="AB mag", choices=["AB mag", "Vega mag", "mJy", "erg / s / cm² / Å"])
    bandpass = serializers.CharField(required=False)
    astrometric_catalog = serializers.CharField(required=False)
    photometry_catalog = serializers.CharField(required=False)
    comments = serializers.CharField(required=False)

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


class GenericHermesDataSerializer(serializers.Serializer):
    references = ReferenceDataSerializer(many=True, required=False)
    extra_data = serializers.JSONField(required=False)
    event_id = serializers.CharField(required=False)
    targets = TargetDataSerializer(many=True, required=False)
    photometry = PhotometryDataSerializer(many=True, required=False)
    spectroscopy = SpectroscopyDataSerialzier(many=True, required=False)
    astrometry = AstrometryDataSerializer(many=True, required=False)

    def validate(self, data):
        # TODO: Add validation if submit_to_tns is set that required fields are set
        # TODO: Add validation if submit_to_mpc is set that required fields are set
        validated_data = super().validate(data)
        target_names = [target.get('name') for target in validated_data.get('targets', [])]
        full_error = {}
        photometry_errors = []
        for photometry in validated_data.get('photometry', []):
            if photometry.get('target_name') not in target_names:
                photometry_errors.append(
                    {'target_name': 'The target_name must reference a name in your target table'}
                )
            else:
                photometry_errors.append({})
        if any(photometry_errors):
            full_error['photometry'] = photometry_errors

        spectroscopy_errors = []
        for spectroscopy in validated_data.get('spectroscopy', []):
            if spectroscopy.get('target_name') not in target_names:
                spectroscopy_errors.append(
                    {'target_name': 'The target_name must reference a name in your target table'}
                )
            else:
                spectroscopy_errors.append({})
        if any(spectroscopy_errors):
            full_error['spectroscopy'] = spectroscopy_errors

        astrometry_errors = []
        for astrometry in validated_data.get('astrometry', []):
            if astrometry.get('target_name') not in target_names:
                astrometry_errors.append(
                    {'target_name': 'The target_name must reference a name in your target table'}
                )
            else:
                astrometry_errors.append({})
        if any(astrometry_errors):
            full_error['astrometry'] = astrometry_errors

        if full_error:
            raise serializers.ValidationError(full_error)

        return validated_data


class HermesMessageSerializer(serializers.Serializer):
    title = serializers.CharField(required=True)
    topic = serializers.CharField(required=True)
    message_text = serializers.CharField(required=False, default='', allow_blank=True)
    submitter = serializers.CharField(required=True)
    authors = serializers.CharField(required=False, default='', allow_blank=True)
    data = GenericHermesDataSerializer(required=False)
    submit_to_tns = serializers.BooleanField(default=False, required=False, write_only=True)
    submit_to_mpc = serializers.BooleanField(default=False, required=False, write_only=True)
