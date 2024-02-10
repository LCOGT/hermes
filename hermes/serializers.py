from hermes.models import Message, NonLocalizedEvent, NonLocalizedEventSequence, Target, Profile, OAuthToken
from hermes.utils import TNS_TYPES
from hermes.tns import get_reverse_tns_values
from hermes.oauth_clients import get_access_token
from rest_framework import serializers
from astropy.coordinates import Longitude, Latitude
from astropy import units
from dateutil.parser import parse
from django.utils.translation import gettext as _
from django.conf import settings

import math
from collections import OrderedDict, defaultdict


class RemoveNullSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        data = super().to_internal_value(data)
        return OrderedDict([(key, data[key]) for key in data if data[key] or data[key] == 0 or data[key] == False])

    def to_representation(self, instance):
        data = super().to_representation(instance)
        return OrderedDict([(key, data[key]) for key in data if data[key] or data[key] == 0 or data[key] == False])


class ProfileSerializer(serializers.ModelSerializer):
    email = serializers.CharField(source='user.email', read_only=True)
    api_token = serializers.CharField(read_only=True)
    can_submit_to_gcn = serializers.SerializerMethodField()
    integrated_apps = serializers.SerializerMethodField()
    tns_bot_api_token = serializers.CharField(required=False, write_only=True)

    class Meta:
        model = Profile
        fields = (
            'api_token', 'email', 'credential_name', 'writable_topics', 'integrated_apps', 'can_submit_to_gcn', 'tns_bot_id',
            'tns_bot_name', 'tns_bot_api_token'
        )

    def get_integrated_apps(self, obj):
        tokens = OAuthToken.objects.filter(user=obj.user)
        integrated_apps = [token.integrated_app for token in tokens]
        if obj.tns_bot_api_token and obj.tns_bot_name and obj.tns_bot_id != -1:
            integrated_apps.append('TNS')
        return integrated_apps

    def get_can_submit_to_gcn(self, obj):
        return OAuthToken.objects.filter(
            user=obj.user, integrated_app=OAuthToken.IntegratedApps.GCN, group_permissions__contains=['gcn.nasa.gov/circular-submitter']
        ).exists()

    def validate(self, data):
        validated_data = super().validate(data)
        if self.context.get('request').method == 'PATCH':
            update_fields = ['tns_bot_id', 'tns_bot_name', 'tns_bot_api_token']
            update_fields_present = [field in validated_data for field in update_fields]
            if any(update_fields_present) and not all(update_fields_present):
                raise serializers.ValidationError(_(
                    'Must update tns_bot_id, tns_bot_name, and tns_bot_api_token all together'
                ))
            if any([field not in update_fields for field in validated_data]):
                raise serializers.ValidationError(_(
                    f"Can only update profile fields: {', '.join(update_fields)}"
                ))
        return validated_data


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
        fdate = float(date)
        if not ((fdate < 2600000 and fdate > 2400000) or (fdate < 150000 and fdate > 1000)):
            raise serializers.ValidationError(_(f"Date {fdate} in JD format must be within bounds of 2400000 to 2600000, and in MJD format within bounds of 15000 to 150000."))
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
        elif validated_data['source'].lower() == 'hop_uuid' and not \
                Message.objects.filter(uuid=validated_data['citation']).exists():
            raise serializers.ValidationError({
                'citation': f"hop_uuid {validated_data['citation']} does not exist"
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
    transient_type = serializers.ChoiceField(required=False, default='Other',
                                             choices=['PSN', 'NUC', 'PNV', 'AGN', 'FRB', 'Other'])
    proprietary_period = serializers.FloatField(required=False, allow_null=True)
    proprietary_period_units = serializers.ChoiceField(required=False, default='Days',
                                                       choices=['Days', 'Months', 'Years'])


class TargetDataSerializer(RemoveNullSerializer):
    name = serializers.CharField(required=True)
    ra = serializers.CharField(required=False, allow_null=True)
    dec = serializers.CharField(required=False, allow_null=True)
    ra_error = serializers.FloatField(required=False, allow_null=True)
    dec_error = serializers.FloatField(required=False, allow_null=True)
    ra_error_units = serializers.ChoiceField(required=False, default='degrees', choices=[
        'degrees', 'mas', 'arcsec', 'arcmin'
    ])
    dec_error_units = serializers.ChoiceField(required=False, default='degrees', choices=[
        'degrees', 'mas', 'arcsec', 'arcmin'
    ])
    pm_ra = serializers.FloatField(required=False, allow_null=True)
    pm_dec = serializers.FloatField(required=False, allow_null=True)
    epoch = serializers.CharField(required=False, default='2000.0')
    new_discovery = serializers.BooleanField(default=False, required=False)
    orbital_elements = OrbitalElementsSerializer(required=False)
    discovery_info = DiscoveryInfoSerializer(required=False)
    distance = serializers.FloatField(required=False, allow_null=True)
    distance_error = serializers.FloatField(required=False, allow_null=True)
    distance_units = serializers.ChoiceField(required=False, allow_null=True, choices=[
        'cm', 'm', 'km', 'pc', 'kpc', 'Mpc', 'Gpc', 'ly', 'au'
    ])
    redshift = serializers.FloatField(required=False, allow_null=True)
    host_name = serializers.CharField(required=False, allow_null=True)
    host_redshift = serializers.FloatField(required=False, allow_null=True)
    aliases = serializers.ListField(child=serializers.CharField(), required=False)
    group_associations = serializers.ListField(child=serializers.CharField(), required=False, allow_null=True)

    def validate_epoch(self, value):
        validate_date(value)
        return value

    def validate(self, data):
        validated_data = super().validate(data)
        if (validated_data.get('ra') is None or validated_data.get('dec') is None):
            if validated_data.get('ra') is not None:
                raise serializers.ValidationError({
                    'dec': ['Must set dec if ra is set']
                })
            elif validated_data.get('dec') is not None:
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


class FileInfoSerializer(RemoveNullSerializer):
    name = serializers.CharField(required=True)
    description = serializers.CharField(required=False, allow_blank=True)
    url = serializers.URLField(required=False)


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
    flux = serializers.ListField(child=serializers.FloatField(), min_length=1, required=False)
    flux_error = serializers.ListField(child=serializers.FloatField(), required=False)
    flux_units = serializers.ChoiceField(required=False, default="mJy", choices=["mJy", "erg / s / cm² / Å"])
    wavelength = serializers.ListField(child=serializers.FloatField(), min_length=1, required=False)
    wavelength_units = serializers.ChoiceField(required=False, default='nm',
                                               choices=['Å', 'nm', 'µm', 'Hz', 'GHz', 'THz'])
    flux_type = serializers.ChoiceField(required=False, default='Fλ', choices=['Fλ', 'Flambda', 'Fν', 'Fnu'])
    classification = serializers.CharField(required=False, allow_null=True)
    proprietary_period = serializers.FloatField(required=False, allow_null=True)
    proprietary_period_units = serializers.ChoiceField(required=False, default='Days',
                                                       choices=['Days', 'Months', 'Years'])
    comments = serializers.CharField(required=False, allow_null=True)
    observer = serializers.CharField(required=False, allow_null=True)
    reducer = serializers.CharField(required=False, allow_null=True)
    spec_type = serializers.ChoiceField(required=False, choices=['Object', 'Host', 'Synthetic', 'Sky', 'Arcs'])
    file_info = FileInfoSerializer(required=False, many=True)

    def validate(self, data):
        validated_data = super().validate(data)
        if ('flux' not in validated_data or validated_data['flux'] == None or len(validated_data['flux']) == 0):
            if ('file_info' not in validated_data or len(validated_data['file_info']) == 0):
                raise serializers.ValidationError({
                    'file_info': [_("Must specify a spectroscopy file to upload or specify one or more flux values")],
                    'flux': [_("Must specify a spectroscopy file to upload or specify one or more flux values")]
                })
        if 'flux_error' in validated_data:
            if len(validated_data.get('flux_error', [])) != len(validated_data.get('flux', [])):
                raise serializers.ValidationError(_('Must have same number of datapoints for flux and flux_error'))
        if len(validated_data.get('flux', [])) != len(validated_data.get('wavelength', [])):
            raise serializers.ValidationError(_('Must have same number of datapoints for flux and wavelength'))

        return validated_data


class AstrometryDataSerializer(CommonDataSerializer):
    ra = serializers.CharField(required=True)
    dec = serializers.CharField(required=True)
    ra_error = serializers.FloatField(required=False, allow_null=True)
    dec_error = serializers.FloatField(required=False, allow_null=True)
    ra_error_units = serializers.ChoiceField(required=False, default='degrees', choices=[
        'degrees', 'mas', 'arcsec', 'arcmin'
    ])
    dec_error_units = serializers.ChoiceField(required=False, default='degrees', choices=[
        'degrees', 'mas', 'arcsec', 'arcmin'
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
    file_info = FileInfoSerializer(required=False, many=True)
    title = serializers.CharField(required=True)
    topic = serializers.CharField(required=True)
    message_text = serializers.CharField(required=False, default='', allow_blank=True)
    submitter = serializers.CharField(required=True)
    authors = serializers.CharField(required=False, default='', allow_blank=True)
    data = GenericHermesDataSerializer(required=False)
    submit_to_tns = serializers.BooleanField(required=False, allow_null=True, write_only=True)
    submit_to_mpc = serializers.BooleanField(required=False, allow_null=True, write_only=True)
    submit_to_gcn = serializers.BooleanField(required=False, allow_null=True, write_only=True)
    # These lists for the GCN are from https://gcn.nasa.gov/docs/circulars/styleguide
    GCN_REQUIRED_KEYS = ["AGILE",
                         "ANTARES",
                         "AXP",
                         "Baksan Neutrino Observatory Alert",
                         "CALET",
                         "Chandra",
                         "Fermi",
                         "FXT",
                         "GRB",
                         "GW",
                         "HAWC",
                         "HST",
                         "IBAS",
                         "IceCube",
                         "INTEGRAL",
                         "IPN",
                         "KAGRA",
                         "KONUS",
                         "LIGO",
                         "LOFAR",
                         "LVC",
                         "LVK",
                         "MAGIC",
                         "MASTER",
                         "MAXI",
                         "Pan-STARRS",
                         "POLAR",
                         "RATIR",
                         "SDSS",
                         "SFXT",
                         "SGR",
                         "Suzaku",
                         "Swift",
                         "transient",
                         "VLA",
                         "VLBI",
                         "XRB",
                         "XRF",
                         "XRT",
                         "XTR",
                         "Virgo",
                         "VLA",
                         "ZTF",
                         ]
    GCN_PROHIBITED_KEYS = ["this is an automatic reply",
                           "automatic reply:",
                           "auto reply",
                           "autoreply",
                           "vacation",
                           "out of the office",
                           "out of office",
                           "out of town",
                           "away from my mail",
                           "away from his e-mail",
                           "away from her e-mail",
                           "away from the office",
                           "away from his office",
                           "away from her office",
                           "traveling until",
                           "no longer receiving mail",
                           "delivery failure notif",
                           "mail delivery failure",
                           "returned mail",
                           "saxzlcnkgzmfpbhvyzsbub",
                           "ponse_automatique",
                           "off-line re:",
                           "re: ",
                           "fwd: ",
                           " r: ",
                           " ris: ",
                           "subject:"
                           ]

    def validate_topic(self, value):
        # When running in dev mode, only allow submissions to hermes.test topic
        if settings.SAVE_TEST_MESSAGES and value != 'hermes.test':
            raise serializers.ValidationError(_("Hermes Dev can only submit to the hermes.test topic."))
        return value

    def validate(self, data):
        # TODO: Add validation if submit_to_mpc is set that required fields are set
        validated_data = super().validate(data)
        request = self.context.get('request')

        if validated_data.get('submit_to_tns'):
            # Do extra TNS submission validation here
            tns_options = get_reverse_tns_values()
            full_error = defaultdict(dict)
            non_field_errors = []

            if not request or not request.user.is_authenticated:
                non_field_errors.append(_('Must be an authenticated user to submit to TNS'))

            if non_field_errors:
                full_error['non_field_errors'] = non_field_errors

            targets = validated_data.get('data', {}).get('targets', [])
            photometry_data = validated_data.get('data', {}).get('photometry', [])
            spectroscopy_data = validated_data.get('data', {}).get('spectroscopy', [])
            target_non_field_errors = []
            photometry_non_field_errors = []
            if len(targets) == 0:
                target_non_field_errors.append(_('Must fill in at least one target entry for TNS submission'))
            if len(photometry_data) == 0 and len(spectroscopy_data) == 0:
                photometry_non_field_errors.append(_('Must fill in at least one photometry or spectroscopy entry for TNS submission'))

            targets_errors = []
            for target in targets:
                target_error = {}
                if not target.get('new_discovery', True):
                    target_error['new_discovery'] = [_("Target new_discovery must be set to True for TNS submission")]
                if target.get('ra') is None:
                    target_error['ra'] = [_("Target ra must be present for TNS submission")]
                if target.get('dec') is None:
                    target_error['dec'] = [_("Target dec must be present for TNS submission")]
                if target.get('group_associations'):
                    groups = target.get('group_associations')
                    bad_groups = [group for group in groups if group not in tns_options.get('groups')]
                    if bad_groups:
                        target_error['group_associations'] = [_(f'Group associations {",".join(bad_groups)} are not valid TNS groups')]

                discovery_info = target.get('discovery_info', {})
                discovery_error = {}
                if not discovery_info or not discovery_info.get('reporting_group'):
                    discovery_error['reporting_group'] = [_("Target must have discovery info reporting group for TNS"
                                                            " submission")]
                elif discovery_info.get('reporting_group') not in tns_options.get('groups'):
                    discovery_error['reporting_group'] = [_(f"Discovery reporting group {discovery_info.get('reporting_group')} is not a valid TNS group")]
                if not discovery_info or not discovery_info.get('discovery_source'):
                    discovery_error['discovery_source'] = [_("Target must have discovery info discovery source for TNS"
                                                             " submission")]
                elif discovery_info.get('discovery_source') not in tns_options.get('groups'):
                    discovery_error['discovery_source'] = [_(f"Discovery source group {discovery_info.get('discovery_source')} is not a valid TNS group")]
                if discovery_error:
                    target_error['discovery_info'] = discovery_error
                targets_errors.append(target_error)
            if any(targets_errors):
                full_error['data']['targets'] = targets_errors

            photometry_errors = []
            has_nondetection = False
            has_detection = False
            for photometry in photometry_data:
                photometry_error = {}
                if photometry.get('brightness'):
                    has_detection = True
                if not photometry.get('instrument'):
                    photometry_error['instrument'] = [_('Photometry must have instrument specified for TNS submission')]
                elif photometry.get('instrument') not in tns_options.get('instruments'):
                    photometry_error['instrument'] = [_(f'Instrument {photometry.get("instrument")} is not a valid TNS instrument')]
                if photometry.get('bandpass') not in tns_options.get('filters'):
                    photometry_error['bandpass'] = [_(f'Bandpass {photometry.get("bandpass")} is not a valid TNS filter')]
                if photometry.get('telescope') and photometry.get('telescope') not in tns_options.get('telescopes'):
                    photometry_error['telescope'] = [_(f'Telescope {photometry.get("telescope")} is not a valid TNS telescope')]
                if photometry.get('limiting_brightness'):
                    has_nondetection = True
                photometry_errors.append(photometry_error)
            if any(photometry_errors):
                full_error['data']['photometry'] = photometry_errors

            spectroscopy_errors = []
            for spectroscopy in spectroscopy_data:
                spectroscopy_error = {}
                classification = spectroscopy.get('classification')
                if classification and classification not in tns_options.get('object_types'):
                    spectroscopy_error['classification'] = [_('Must be one of the TNS classification object_types for TNS'
                                                              ' submission')]
                if not spectroscopy.get('instrument'):
                    spectroscopy_error['instrument'] = [_('Spectroscopy must have instrument specified for TNS'
                                                          ' submission')]
                if not spectroscopy.get('observer'):
                    spectroscopy_error['observer'] = [_('Spectroscopy must have observer specified for TNS submission')]
                if not spectroscopy.get('reducer'):
                    spectroscopy_error['reducer'] = [_('Spectroscopy must have reducer specified for TNS submission')]
                if not spectroscopy.get('spec_type'):
                    spectroscopy_error['spec_type'] = [_('Spectroscopy must have spec_type specified for TNS'
                                                         ' submission')]
                spectroscopy_errors.append(spectroscopy_error)
            if any(spectroscopy_errors):
                full_error['data']['spectroscopy'] = spectroscopy_errors

            if not validated_data.get('authors'):
                full_error['authors'] = [_('Must set an author / reporter for TNS submission')]

            if not has_nondetection:
                photometry_non_field_errors.append(_(f'At least one photometry nondetection / limiting_brightness must be specified for TNS submission'))

            if not has_detection:
                photometry_non_field_errors.append(_(f'At least one photometry detection / brightness must be specified for TNS submission'))

            if target_non_field_errors:
                full_error['target_non_field_errors'] = target_non_field_errors

            if photometry_non_field_errors:
                full_error['photometry_non_field_errors'] = photometry_non_field_errors

            if full_error:
                raise serializers.ValidationError(full_error)
        if validated_data.get('submit_to_gcn'):
            non_field_errors = []

            if not request or not request.user.is_authenticated:
                non_field_errors.append(_('Must be an authenticated user to submit to GCN'))
            else:
                # Verify that the user has a valid GCN integration oauth access_token to submit with:
                token = get_access_token(request.user, OAuthToken.IntegratedApps.GCN)
                if not token:
                    non_field_errors.append(_('Must register a valid GCN account on your Profile page to submit to GCN'))

            full_error = defaultdict(dict)
            # Validate that there is an author and message text set
            if not validated_data.get('authors'):
                full_error['authors'] = [_('Authors must be set to submit to GCN')]

            if not validated_data.get('message_text'):
                full_error['message_text'] = [_('Message text must be set to submit to GCN')]

            # Validate the title for GCN submission (which appears to be the only form validation the GCN does)
            title = validated_data.get('title', '')
            if len(title) == 0:
                full_error['title'] = [_('Title must be set to submit to GCN')]
            if not any(key.lower() in title.lower() for key in self.GCN_REQUIRED_KEYS):
                # Set the gcn title errors to non field errors to correctly render the html in the error message
                non_field_errors.append(_('Title must contain one of allowed subject keywords from the'
                                    ' <a href="https://gcn.nasa.gov/docs/circulars/styleguide#message-content" target="_blank">GCN Style Guide</a>'
                                    ' to submit to GCN.'))
            for key in self.GCN_PROHIBITED_KEYS:
                if key in title.lower():
                    non_field_errors.append(_('Title cannot contain the prohibited keyword "{}". Please see the'
                                        ' <a href="https://gcn.nasa.gov/docs/circulars/styleguide#message-content" target="_blank">GCN Style'
                                        ' Guide</a>.'.format(key)))
            if non_field_errors:
                full_error['non_field_errors'] = non_field_errors
            if full_error:
                raise serializers.ValidationError(full_error)
        # Remove the flags from the serialized response sent through hop
        if 'submit_to_tns' in validated_data:
            del validated_data['submit_to_tns']
        if 'submit_to_mpc' in validated_data:
            del validated_data['submit_to_mpc']
        if 'submit_to_gcn' in validated_data:
            del validated_data['submit_to_gcn']

        return validated_data
