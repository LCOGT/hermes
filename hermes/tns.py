import requests
from urllib.parse import urljoin
from dateutil.parser import parse

from django.core.cache import cache
from django.conf import settings

import logging
logger = logging.getLogger(__name__)


# Need to spoof a web based user agent or TNS will block the request :(
SPOOF_USER_AGENT = 'Mozilla/5.0 (X11; Linux i686; rv:110.0) Gecko/20100101 Firefox/110.0.'


def populate_tns_values():
    all_tns_values = {}
    reversed_tns_values = {}
    try:
        resp = requests.get(urljoin(settings.TNS_BASE_URL, 'api/values/'),
                            headers={'user-agent': SPOOF_USER_AGENT})
        resp.raise_for_status()
        all_tns_values = resp.json().get('data', {})
        reversed_tns_values = reverse_tns_values(all_tns_values)
        cache.set("all_tns_values", all_tns_values, 3600)
        cache.set("reverse_tns_values", reversed_tns_values, 3600)
    except Exception as e:
            logging.warning(f"Failed to retrieve tns values: {repr(e)}")

    return all_tns_values, reversed_tns_values


def get_tns_values():
    """ Retrieve the TNS options. These are cached for one hour. """
    all_tns_values = cache.get("all_tns_values", {})
    if not all_tns_values:
        all_tns_values, _ = populate_tns_values()

    return all_tns_values


def get_reverse_tns_values():
    """ Retrieve the reverse mapping of TNS options used to go from option to value.
        I.e. reversed_tns_values['groups'] = {
            'group name 1': 1,
            'group name 2': 4,
            'group whatever': 129
        }
    """
    reversed_tns_values = cache.get("reverse_tns_values", {})
    if not reversed_tns_values:
        _, reversed_tns_values = populate_tns_values()

    return reversed_tns_values


def reverse_tns_values(all_tns_values):
    reversed_tns_values = {}
    for key, values in all_tns_values.items():
        if isinstance(values, list):
            reversed_tns_values[key] = {value: index for index, value in enumerate(values)}
        elif isinstance(values, dict):
            reversed_tns_values[key] = {v: k for k, v in values.items()}
    return reversed_tns_values


def parse_date(date):
    parsed_date = None
    try:
        parsed_date = float(date)
    except ValueError:
        try:
            parsed_date = parse(date)
        except ValueError:
            pass
    return parsed_date


def get_earliest_photometry(photometry_list, nondetection=False):
    """ Retrieve the earliest detection or nondetection photometry from a list """
    earliest_photometry = photometry_list[0]
    earliest_date = parse_date(photometry_list[0].get('date_obs'))
    for photometry in photometry_list[1:]:
        if not nondetection and not photometry.get('brightness', 0):
            continue
        elif nondetection and not photometry.get('limiting_brightness', 0):
            continue
        date = parse_date(photometry.get('date_obs'))
        if not date:
            continue
        if date < earliest_date:
            earliest_date = date
            earliest_photometry = photometry
    
    return earliest_photometry


def convert_flux_units(hermes_units):
    """ Convert from hermes supported flux units into TNS units value """
    if hermes_units == 'AB mag':
        return '1'
    elif hermes_units == 'Vega mag':
        return '3'
    elif hermes_units == 'mJy':
        return '9'
    elif hermes_units == 'erg / s / cm² / Å':
        return '6'


def convert_hermes_message_to_tns(hermes_message):
    """ Converts from hermes message format into TNS at report format """
    # TODO: Add support for associated files
    # TODO: Add support for classification or frb reports
    at_report = {}
    tns_options = get_reverse_tns_values()
    data = hermes_message.get('data', {})
    for target in data.get('targets', []):
        photometry_list = [photometry for photometry in data.get('photometry', []) if photometry.get('target_name') == target.get('name')]
        earliest_photometry = get_earliest_photometry(photometry_list)
        report = {}
        report['ra'] = {
            'value': target.get('ra'),
            'error': target.get('ra_error'),
            'units': target.get('ra_error_units')
        }
        report['dec'] = {
            'value': target.get('dec'),
            'error': target.get('dec_error'),
            'units': target.get('dec_error_units')
        }
        discovery_info = target.get('discovery_info', {})
        report['reporting_group_id'] = str(tns_options.get('groups', {}).get(discovery_info.get('reporting_group'), -1))
        report['discovery_data_source_id'] = str(tns_options.get('groups', {}).get(discovery_info.get('discovery_source'), -1))
        report['reporter'] = hermes_message.get('submitter')
        report['discovery_datetime'] = earliest_photometry.get('date_obs')
        report['at_type'] = str(tns_options.get('at_types', {}).get(discovery_info.get('transient_type'), -1))
        report['host_name'] = target.get('host_name', '')
        report['host_redshift'] = target.get('host_redshift', '')
        report['transient_redshift'] = target.get('redshift', '')
        report['internal_name'] = target.get('name', '')
        report['remarks'] = hermes_message.get('message_text')
        groups = target.get('group_associations', [])
        report['proprietary_period_groups'] = [str(tns_options.get('groups', {}).get(group, -1)) for group in groups]
        report['proprietary_period'] = {
            'proprietary_period_value': discovery_info.get('proprietary_period'),
            'proprietary_period_units': discovery_info.get('proprietary_period_units').lower()
        }
        earliest_nondetection = get_earliest_photometry(photometry_list, nondetection=True)
        if earliest_nondetection.get('limiting_brightness', 0):
            report['nondetection'] = {
                'obsdate': earliest_nondetection.get('date_obs'),
                'limiting_flux': earliest_nondetection.get('limiting_brightness'),
                'flux_units': convert_flux_units(earliest_nondetection.get('limiting_brightness_unit', 'AB mag')),
                'filter_value': str(tns_options.get('filters', {}).get(earliest_nondetection.get('bandpass'))),
                'instrument_value': str(tns_options.get('instruments', []).get(earliest_nondetection.get('instrument',))),
                'exptime': str(earliest_nondetection.get('exposure_time', '')),
                'observer': earliest_nondetection.get('observer', ''),
                'comments': earliest_nondetection.get('comments', ''),
                'archiveid': '',
                'archival_remarks': ''
            }
        report['photometry'] = {'photometry_group': {}}
        i = 0
        for photometry in photometry_list:
            if photometry.get('brightness'):
                report_photometry = {
                    'obsdate': photometry.get('date_obs'),
                    'flux': photometry.get('brightness', ''),
                    'flux_error': photometry.get('brightness_error', ''),
                    'limiting_flux': photometry.get('limiting_brightness', ''),
                    'flux_units': convert_flux_units(photometry.get('brightness')),
                    'filter_value': str(tns_options.get('filters', {}).get(photometry.get('bandpass'))),
                    'instrument_value': str(tns_options.get('instruments', {}).get(photometry.get('instrument', ''))),
                    'exptime': str(photometry.get('exposure_time', '')),
                    'observer': photometry.get('observer', ''),
                    'comments': photometry.get('comments', '')
                }
                report['photometry']['photometry_group'][str(i)] = report_photometry
                i += 1
        at_report[str(len(at_report))] = report
    return at_report
