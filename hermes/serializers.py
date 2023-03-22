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
from collections import OrderedDict


class RemoveNullSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        data = super().to_internal_value(data)
        return OrderedDict([(key, data[key]) for key in data if data[key]])

    def to_representation(self, instance):
        data = super().to_representation(instance)
        return OrderedDict([(key, data[key]) for key in data if data[key]])


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
            raise serializers.ValidationError(f"{date} does not parse with dateutil.parser.parse. Please specify the date in a standard format or as a JD.")


class ReferenceDataSerializer(RemoveNullSerializer):
    source = serializers.CharField(required=False, allow_null=True)
    citation = serializers.CharField(required=False, allow_null=True)
    url = serializers.URLField(required=False, allow_null=True)

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

class OrbitalElementsSerializer(RemoveNullSerializer):
    epoch_of_elements = serializers.CharField(required=True)
    orbital_inclination = serializers.FloatField(required=True, min_value=0.0, max_value=180.0)
    longitude_of_the_ascending_node = serializers.FloatField(required=True, min_value=0.0, max_value=360.0)
    argument_of_the_perihelion = serializers.FloatField(required=True, min_value=0.0, max_value=360.0)
    eccentricity = serializers.FloatField(required=True, min_value=0.0)
    semimajor_axis = serializers.FloatField(required=False, allow_null=True)
    mean_anomaly = serializers.FloatField(required=False, min_value=0.0, max_value=360.0, allow_null=True)
    perihelion_distance = serializers.FloatField(required=False, allow_null=True)
    epoch_of_perihelion = serializers.CharField(required=False, allow_null=True)

    def validate_epoch_of_elements(self, value):
        validate_date(value)
        return value

    def validate_epoch_of_perihelion(self, value):
        validate_date(value)
        return value

    def validate(self, data):
        validated_data = super().validate(data)
        if not ((validated_data.get('semimajor_axis') and validated_data.get('mean_anomaly')) or (
            validated_data.get('perihelion_distance') and validated_data.get('epoch_of_perihelion'))):
            if validated_data.get('semimajor_axis'):
                raise serializers.ValidationError({
                    'mean_anomaly': ['Must set mean_anomaly when semimajor_axis is set']
                })
            if validated_data.get('mean_anomaly'):
                raise serializers.ValidationError({
                    'semimajor_axis': ['Must set semimajor_axis when mean_anomaly is set']
                })
            if validated_data.get('perihelion_distance'):
                raise serializers.ValidationError({
                    'epoch_of_perihelion': ['Must set epoch_of_perihelion when perihelion_distance is set']
                })
            if validated_data.get('epoch_of_perihelion'):
                raise serializers.ValidationError({
                    'perihelion_distance': ['Must set perihelion_distance when epoch_of_perihelion is set']
                })
            raise serializers.ValidationError({
                'mean_anomaly': ["Must set mean_anomaly/semimajor_axis or epoch_of_perihelion/perihelion_distance"],
                'semimajor_axis': ["Must set mean_anomaly/semimajor_axis or epoch_of_perihelion/perihelion_distance"],
                'epoch_of_perihelion': ["Must set mean_anomaly/semimajor_axis or epoch_of_perihelion/perihelion_distance"],
                'perihelion_distance': ["Must set mean_anomaly/semimajor_axis or epoch_of_perihelion/perihelion_distance"],
            })

        return validated_data


class DiscoveryInfoSerializer(RemoveNullSerializer):
    reporting_group = serializers.CharField(required=False, allow_null=True)
    discovery_source = serializers.CharField(required=False, allow_null=True)
    transient_type = serializers.ChoiceField(required=False, default='Other', choices=['PSN', 'nuc', 'PNV', 'AGN', 'Other'])
    proprietary_period = serializers.FloatField(required=False, allow_null=True)
    proprietary_period_units = serializers.ChoiceField(required=False, default='Days', choices=['Seconds', 'Days', 'Years'])


class TargetDataSerializer(RemoveNullSerializer):
    name = serializers.CharField(required=True)
    ra = serializers.CharField(required=False, allow_null=True)
    dec = serializers.CharField(required=False, allow_null=True)
    ra_error = serializers.FloatField(required=False, allow_null=True)
    dec_error = serializers.FloatField(required=False, allow_null=True)
    ra_error_units = serializers.ChoiceField(required=False, default='degrees', choices=[
        'degrees', 'marcsec', 'arcsec', 'arcmin'
    ])
    dec_error_units = serializers.ChoiceField(required=False, default='degrees', choices=[
        'degrees', 'marcsec', 'arcsec', 'arcmin'
    ])
    pm_ra = serializers.FloatField(required=False, allow_null=True)
    pm_dec = serializers.FloatField(required=False, allow_null=True)
    epoch = serializers.CharField(required=False, default='2000.0')
    new_discovery = serializers.BooleanField(default=False, required=False)
    orbital_elements = OrbitalElementsSerializer(required=False)
    discovery_info = DiscoveryInfoSerializer(required=False)
    redshift = serializers.FloatField(required=False, allow_null=True)
    host_name = serializers.CharField(required=False, allow_null=True)
    host_redshift = serializers.FloatField(required=False, allow_null=True)
    aliases = serializers.ListField(child=serializers.CharField(), required=False)
    group_associations = serializers.CharField(required=False, allow_null=True)

    def validate_epoch(self, value):
        validate_date(value)
        return value

    def validate(self, data):
        validated_data = super().validate(data)
        if not (validated_data.get('ra') and validated_data.get('dec')):
            if validated_data.get('ra'):
                raise serializers.ValidationError({
                    'dec': ['Must set dec if ra is set']
                })
            elif validated_data.get('dec'):
                raise serializers.ValidationError({
                    'ra': ['Must set ra if dec is set']
                })
            if not validated_data.get('orbital_elements'):
                raise serializers.ValidationError({
                    'ra': ['ra/dec or orbital elements are required'],
                    'dec': ['ra/dec or orbital elements are required'],
                    'orbital_elements': {'non_field_errors': ['ra/dec or orbital elements are required']}
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

class CommonDataSerializer(RemoveNullSerializer):
    target_name = serializers.CharField(required=True)
    date_obs = serializers.CharField(required=True)
    telescope = serializers.CharField(required=False, default='', allow_blank=True, allow_null=True)
    instrument = serializers.CharField(required=False, default='', allow_blank=True, allow_null=True)

    def validate_date_obs(self, value):
        validate_date(value)
        return value

    def validate(self, data):
        validated_data = super().validate(data)
        if not (validated_data.get('instrument') or validated_data.get('telescope')):
            error_msg = _("Must have at least one of telescope or instrument set")
            raise serializers.ValidationError({'telescope': [error_msg], 'instrument': [error_msg]})
        return validated_data


class PhotometryDataSerializer(CommonDataSerializer):
    bandpass = serializers.CharField(required=True)
    brightness = serializers.FloatField(required=False, allow_null=True)
    brightness_error = serializers.FloatField(required=False, allow_null=True)
    brightness_unit = serializers.ChoiceField(required=False, default="AB mag", choices=["AB mag", "Vega mag", "mJy", "erg / s / cm² / Å"])
    exposure_time = serializers.FloatField(required=False, allow_null=True)
    observer = serializers.CharField(required=False, allow_null=True)
    comments = serializers.CharField(required=False, allow_null=True)
    limiting_brightness = serializers.FloatField(required=False, allow_null=True)
    limiting_brightness_error = serializers.FloatField(required=False, allow_null=True)
    limiting_brightness_unit = serializers.ChoiceField(required=False, default="AB mag", choices=["AB mag", "Vega mag", "mJy", "erg / s / cm² / Å"])
    catalog = serializers.CharField(required=False, allow_null=True)
    group_associations = serializers.CharField(required=False, allow_null=True)

    def validate(self, data):
        validated_data = super().validate(data)
        if not (validated_data.get('brightness') or validated_data.get('limiting_brightness')):
            raise serializers.ValidationError({
                'brightness': ['brightness or limiting_brightness are required'],
                'limiting_brightness': ['brightness or limiting_brightness are required']
            })

        return validated_data


class SpectroscopyDataSerializer(CommonDataSerializer):
    setup = serializers.CharField(required=False, allow_null=True)
    exposure_time = serializers.FloatField(required=False, allow_null=True)
    flux = serializers.ListField(child=serializers.FloatField(), min_length=1, required=True)
    flux_error = serializers.ListField(child=serializers.FloatField(), required=False)
    flux_units = serializers.ChoiceField(required=False, default="mJy", choices=["mJy", "erg / s / cm² / Å"])
    wavelength = serializers.ListField(child=serializers.FloatField(), min_length=1, required=True)
    wavelength_units = serializers.ChoiceField(required=False, default='nm', choices=['Å', 'nm', 'µm'])
    flux_type = serializers.ChoiceField(required=False, default='Fλ', choices=['Fλ', 'Flambda', 'Fν', 'Fnu'])
    classification = serializers.CharField(required=False, allow_null=True)
    proprietary_period = serializers.FloatField(required=False, allow_null=True)
    proprietary_period_units = serializers.ChoiceField(required=False, default='Days', choices=['Seconds', 'Days', 'Years'])
    comments = serializers.CharField(required=False, allow_null=True)
    group_associations = serializers.CharField(required=False, allow_null=True)
    observer = serializers.CharField(required=False, allow_null=True)
    reducer = serializers.CharField(required=False, allow_null=True)
    spec_type = serializers.ChoiceField(required=False, choices=['Object', 'Host', 'Synthetic', 'Sky', 'Arcs'])

    def validate(self, data):
        validated_data = super().validate(data)
        if 'flux_error' in validated_data:
            if len(validated_data['flux_error']) != len(validated_data['flux']):
                raise serializers.ValidationError(_('Must have same number of datapoints for flux and flux_error'))
        if len(validated_data['flux']) != len(validated_data['wavelength']):
            raise serializers.ValidationError(_('Must have same number of datapoints for flux and wavelength'))

        return validated_data


class AstrometryDataSerializer(CommonDataSerializer):
    ra = serializers.CharField(required=True)
    dec = serializers.CharField(required=True)
    ra_error = serializers.FloatField(required=False, allow_null=True)
    dec_error = serializers.FloatField(required=False, allow_null=True)
    ra_error_units = serializers.ChoiceField(required=False, default='degrees', choices=[
        'degrees', 'marcsec', 'arcsec', 'arcmin'
    ])
    dec_error_units = serializers.ChoiceField(required=False, default='degrees', choices=[
        'degrees', 'marcsec', 'arcsec', 'arcmin'
    ])
    mpc_sitecode = serializers.CharField(required=False, allow_null=True)
    catalog = serializers.CharField(required=False, allow_null=True)
    comments = serializers.CharField(required=False, allow_null=True)

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


class GenericHermesDataSerializer(RemoveNullSerializer):
    references = ReferenceDataSerializer(many=True, required=False)
    extra_data = serializers.JSONField(required=False)
    event_id = serializers.CharField(required=False, allow_null=True)
    targets = TargetDataSerializer(many=True, required=False)
    photometry = PhotometryDataSerializer(many=True, required=False)
    spectroscopy = SpectroscopyDataSerializer(many=True, required=False)
    astrometry = AstrometryDataSerializer(many=True, required=False)

    def validate(self, data):
        validated_data = super().validate(data)
        target_names = [target.get('name') for target in validated_data.get('targets', [])]
        full_error = {}
        
        target_errors = []
        for target_name in target_names:
            if target_names.count(target_name) > 1:
                target_errors.append(
                    {'name': ['The target name must be unique within the submission']}
                )
            else:
                target_errors.append({})
        if any(target_errors):
            full_error['targets'] = target_errors
        
        photometry_errors = []
        for photometry in validated_data.get('photometry', []):
            if photometry.get('target_name') not in target_names:
                photometry_errors.append(
                    {'target_name': ['The target_name must reference a name in your target table']}
                )
            else:
                photometry_errors.append({})
        if any(photometry_errors):
            full_error['photometry'] = photometry_errors

        spectroscopy_errors = []
        for spectroscopy in validated_data.get('spectroscopy', []):
            if spectroscopy.get('target_name') not in target_names:
                spectroscopy_errors.append(
                    {'target_name': ['The target_name must reference a name in your target table']}
                )
            else:
                spectroscopy_errors.append({})
        if any(spectroscopy_errors):
            full_error['spectroscopy'] = spectroscopy_errors

        astrometry_errors = []
        for astrometry in validated_data.get('astrometry', []):
            if astrometry.get('target_name') not in target_names:
                astrometry_errors.append(
                    {'target_name': ['The target_name must reference a name in your target table']}
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

    def validate(self, data):
        # TODO: Add validation if submit_to_mpc is set that required fields are set
        validated_data = super().validate(data)
        if validated_data.get('submit_to_tns'):
            # Do extra TNS submission validation here
            targets = validated_data.get('data', {}).get('targets', [])
            if len(targets) == 0:
                raise serializers.ValidationError(_('Must fill in at least one target for TNS submission'))

            full_error = {}
            targets_errors = []
            for target in targets:
                target_error = {}
                if not target.get('ra'):
                    target_error['ra'] = [_("Target ra must be present for TNS submission")]
                if not target.get('dec'):
                    target_error['dec'] = [_("Target dec must be present for TNS submission")]
                discovery_info = target.get('discovery_info', {})
                discovery_error = {}
                if not discovery_info or not discovery_info.get('reporting_group'):
                    discovery_error['reporting_group'] = [_("Target must have discovery info reporting group for TNS submission")]
                if not discovery_info or not discovery_info.get('discovery_source'):
                    discovery_error['discovery_source'] = [_("Target must have discovery info discovery source for TNS submission")]
                if discovery_error:
                    target_error['discovery_info'] = discovery_error
                targets_errors.append(target_error)
            if any(targets_errors):
                full_error['targets'] = targets_errors

            spectroscopy_errors = []
            for spectroscopy in validated_data.get('data', {}).get('spectroscopy', []):
                classification = spectroscopy.get('classification')
                if classification and classification not in TNS_TYPES:
                    spectroscopy_errors.append(
                        {'classification': [_('Must be one of the TNS classification types for TNS submission')]}
                    )
                else:
                    spectroscopy_errors.append({})
            if any(spectroscopy_errors):
                full_error['spectroscopy'] = spectroscopy_errors

            if full_error:
                raise serializers.ValidationError({
                    'data': full_error
                })

        return validated_data
