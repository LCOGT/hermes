import requests
import time
import json
from urllib.parse import urljoin
from dateutil.parser import parse
from astropy.time import Time

from django.core.cache import cache
from django.conf import settings

import logging
logger = logging.getLogger(__name__)


# Need to spoof a web based user agent or TNS will block the request :(
SPOOF_USER_AGENT = 'Mozilla/5.0 (X11; Linux i686; rv:110.0) Gecko/20100101 Firefox/110.0.'


class BadTnsRequest(Exception):
    """ This Exception will be raised by errors during the TNS submission process """
    pass


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
    """ Turn a float / string date into a python datetime. Supports mjd, jd, and parseable date formats"""
    parsed_date = None
    try:
        parsed_date = float(date)
        if parsed_date > 2400000:
            parsed_date = Time(parsed_date, format='jd').datetime
        else:
            parsed_date = Time(parsed_date, format='mjd').datetime
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
        report['reporter'] = hermes_message.get('authors')
        report['discovery_datetime'] = parse_date(earliest_photometry.get('date_obs')).strftime('%Y-%m-%d %H:%M:%S')
        report['at_type'] = str(tns_options.get('at_types', {}).get(discovery_info.get('transient_type'), -1))
        report['host_name'] = target.get('host_name', '')
        report['host_redshift'] = target.get('host_redshift', '')
        report['transient_redshift'] = target.get('redshift', '')
        report['internal_name'] = target.get('name', '')
        report['remarks'] = hermes_message.get('message_text')
        groups = target.get('group_associations', [])
        report['proprietary_period_groups'] = [str(tns_options.get('groups', {}).get(group, -1)) for group in groups]
        if discovery_info.get('proprietary_period'):
            report['proprietary_period'] = {
                'proprietary_period_value': str(int(discovery_info.get('proprietary_period'))),
                'proprietary_period_units': discovery_info.get('proprietary_period_units').lower()
            }
        earliest_nondetection = get_earliest_photometry(photometry_list, nondetection=True)
        if earliest_nondetection.get('limiting_brightness', 0):
            report['non_detection'] = {
                'obsdate': parse_date(earliest_nondetection.get('date_obs')).strftime('%Y-%m-%d %H:%M:%S'),
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
                    'obsdate': parse_date(photometry.get('date_obs')).strftime('%Y-%m-%d %H:%M:%S'),
                    'flux': photometry.get('brightness', ''),
                    'flux_error': photometry.get('brightness_error', ''),
                    'limiting_flux': photometry.get('limiting_brightness', ''),
                    'flux_units': convert_flux_units(photometry.get('brightness_unit', 'AB mag')),
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


def get_tns_marker():
    tns_marker = 'tns_marker{"tns_id": "' + str(settings.TNS_CREDENTIALS.get('id')) + '", "type": "bot", "name": "' + settings.TNS_CREDENTIALS.get('name') + '"}'
    return tns_marker


def parse_object_from_tns_response(response_json):
    at_report_response = response_json.get('data', {}).get('feedback', {}).get('at_report', {})[0]
    for value in at_report_response.values():
        if isinstance(value, dict) and 'objname' in value:
            return value['objname']
    return None


def submit_to_tns(at_report):
    """ Submit a tns formatted message to the tns server, and returns the TNS object name """
    data = {'at_report': at_report}
    payload = {
        'api_key': settings.TNS_CREDENTIALS.get('api_token'),
        'data': json.dumps(data, indent=4)
    }
    url = urljoin(settings.TNS_BASE_URL, 'api/bulk-report')
    headers = {'User-Agent': get_tns_marker()}
    try:
        response = requests.post(url, headers = headers, data = payload)
        response.raise_for_status()
        report_id = response.json()['data']['report_id']
    except Exception:
        raise Exception

    attempts = 0
    object_name = None
    reply_url = urljoin(settings.TNS_BASE_URL, 'api/bulk-report-reply')
    reply_data = {'api_key': settings.TNS_CREDENTIALS.get('api_token'), 'report_id': report_id}
    # TNS Submissions return immediately with an id, which you must then check to see if the message
    # was processed, and if it was accepted or rejected. Here we check up to 10 times, waiting 1s
    # between checks. Under normal circumstances, it should be processed within a few seconds.
    while attempts < 10:
        response = requests.post(reply_url, headers = headers, data = reply_data)
        attempts += 1
        # A 404 response means the report has not been processed yet
        if response.status_code == 404:
            time.sleep(1)
        # A 400 response means the report failed with certain errors
        elif response.status_code == 400:
            raise BadTnsRequest(f"TNS submission failed with feedback: {response.json().get('data', {}).get('feedback', {})}")
        # A 200 response means the report was successful and we can parse out the object name
        elif response.status_code == 200:
            object_name = parse_object_from_tns_response(response.json())
            break
    if not object_name:
        raise BadTnsRequest(f"TNS submission failed to be processed within 10 seconds. The report_id = {report_id}")
    return object_name
