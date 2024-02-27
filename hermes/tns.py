import requests
import time
from datetime import datetime
import json
from urllib.parse import urljoin
from dateutil.parser import parse
from astropy.time import Time
from collections import defaultdict

from django.core.cache import cache
from django.conf import settings
from django.utils import timezone

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
    earliest_photometry = None
    earliest_date = datetime.max.replace(tzinfo=timezone.utc)
    for photometry in photometry_list:
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


def convert_classification_hermes_message_to_tns(hermes_message, target_filenames_mapping, spectroscopy_filenames_mapping):
    """ Converts from a hermes message format into a TNS classification report format """
    report_payload = {}
    tns_options = get_reverse_tns_values()
    data = hermes_message.get('data', {})
    spectroscopy_by_target = defaultdict(list)
    for spectra in data.get('spectroscopy', []):
        spectroscopy_by_target[spectra['target_name']].append(spectra)
    targets_by_name = {target['name']: target for target in data.get('targets', [])}

    for k, target in enumerate(targets_by_name.values()):
        if target['name'] in spectroscopy_by_target:
            # This means we have at least one spectroscopy datum for this target, so make a classification report from it
            classification_report = {
                'related_files': {},
                'spectra': {'spectra-group': {}}
            }
            discovery_info = target.get('discovery_info', {})
            groups = target.get('group_associations', [])
            classification_report['name'] = target['name']
            classification_report['classifier'] = hermes_message.get('authors')
            classification_report['groupid'] = str(tns_options.get('groups', {}).get(discovery_info.get('reporting_group'), -1))
            classification_report['class_proprietary_period_groups'] = [str(tns_options.get('groups', {}).get(group, -1)) for group in groups]
            classification_report['remarks'] = target.get('comments', '')
            if target.get('redshift'):
                classification_report['redshift'] = target.get('redshift')

            first_spectra = spectroscopy_by_target[target['name']][0]
            # Set classification object_type from the first spectrum
            classification_report['objtypeid'] = str(tns_options.get('object_types', {}).get(first_spectra.get('classification'), -1))
            # Proprietary period of the classification uses the targets discovery info proprietary period but should be left to 0 usually
            classification_report['class_proprietary_period'] = {
                'class_proprietary_period_value': str(discovery_info.get('proprietary_period', 0)),
                'class_proprietary_period_units': discovery_info.get('proprietary_period_units', 'Days').lower()
            }
            for i, spectra in enumerate(spectroscopy_by_target[target['name']]):
                spectra_report = {
                    'obsdate': parse_date(spectra.get('date_obs')).strftime('%Y-%m-%d %H:%M:%S'),
                    'instrumentid': str(tns_options.get('instruments', {}).get(spectra.get('instrument'))),
                    'exptime': str(spectra.get('exposure_time', '')),
                    'observer': spectra.get('observer'),
                    'spectypeid': str(tns_options.get('spectra_types', {}).get(spectra.get('spec_type'))),
                    'remarks': spectra.get('comments', ''),
                    'spec_proprietary_period': {
                        'spec_proprietary_period_value': str(spectra.get('proprietary_period', 0)),
                        'spec_proprietary_period_units': spectra.get('proprietary_period_units', 'Days').lower()
                    }
                }
                if spectra.get('reducer'):
                    spectra_report['reducer'] = spectra.get('reducer')
                # Now add either an ascii or fits file to the payload based on which it was that was added
                for file_info in spectra.get('file_info', []):
                    if '.ascii' in file_info.get('name') or '.txt' in file_info.get('name'):
                        if file_info.get('name') in spectroscopy_filenames_mapping:
                            spectra_report['ascii_file'] = spectroscopy_filenames_mapping[file_info.get('name')]
                    elif '.fits' in file_info.get('name'):
                        if file_info.get('name') in spectroscopy_filenames_mapping:
                            spectra_report['fits_file'] = spectroscopy_filenames_mapping[file_info.get('name')]
                classification_report['spectra']['spectra-group'][str(i)] = spectra_report
            # Now add the related files associated with a target
            for i, file_info in enumerate(target.get('file_info', [])):
                if target_filenames_mapping and file_info.get('name') in target_filenames_mapping:
                    classification_report['related_files'][str(i)] = {
                        'related_file_name': target_filenames_mapping[file_info.get('name')],
                        'related_file_comments': file_info.get('description', '')
                    }
            report_payload[str(k)] = classification_report

    return report_payload


def convert_discovery_hermes_message_to_tns(hermes_message, filenames_mapping):
    """ Converts from a hermes message format into a TNS AT (new discovery) report format """
    at_report = {}
    tns_options = get_reverse_tns_values()
    data = hermes_message.get('data', {})
    for target in data.get('targets', []):
        photometry_list = [photometry for photometry in data.get('photometry', []) if photometry.get('target_name') == target.get('name')]
        earliest_photometry = get_earliest_photometry(photometry_list)
        report = {'related_files': {}}
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
        report['remarks'] = target.get('comments', '')
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
                'instrument_value': str(tns_options.get('instruments', {}).get(earliest_nondetection.get('instrument'))),
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

        for i, file_info in enumerate(target.get('file_info', [])):
            if filenames_mapping and file_info.get('name') in filenames_mapping:
                report['related_files'][str(i)] = {
                    'related_file_name': filenames_mapping[file_info.get('name')],
                    'related_file_comments': file_info.get('description')
                }

        at_report[str(len(at_report))] = report
    return at_report


def get_tns_marker(request):
    if (request.user.is_authenticated and request.user.profile.tns_bot_id != -1
        and request.user.profile.tns_bot_name and request.user.profile.tns_bot_api_token):
        tns_marker = 'tns_marker{"tns_id": "' + str(request.user.profile.tns_bot_id) + '", "type": "bot", "name": "' + request.user.profile.tns_bot_name + '"}'
    else:
        tns_marker = 'tns_marker{"tns_id": "' + str(settings.TNS_CREDENTIALS.get('id')) + '", "type": "bot", "name": "' + settings.TNS_CREDENTIALS.get('name') + '"}'
    return tns_marker


def get_tns_api_token(request):
    if (request.user.is_authenticated and request.user.profile.tns_bot_id != -1
        and request.user.profile.tns_bot_name and request.user.profile.tns_bot_api_token):
        return request.user.profile.tns_bot_api_token
    else:
        return settings.TNS_CREDENTIALS.get('api_token')


def parse_object_from_tns_response(response_json):
    at_report_response = response_json.get('data', {}).get('feedback', {}).get('at_report', [])
    object_names = []
    for at_report_feedback in at_report_response:
        for value in at_report_feedback.values():
            if isinstance(value, dict) and 'objname' in value:
                object_names.append(value['objname'])
    return object_names


def submit_files_to_tns(request, files):
    """ Takes in a list of Django InMemoryUploadedFile objects, and submits those to TNS.
        Returns a dict of raw filenames to TNS filenames for those files.
    """
    url = urljoin(settings.TNS_BASE_URL, 'api/file-upload')
    headers = {'User-Agent': get_tns_marker(request)}
    payload = {'api_key': get_tns_api_token(request)}
    files_data = {}
    for i, file in enumerate(files):
        key = f"files[{str(i)}]"
        files_data[key] = (file.name, file.file, file.content_type)
    try:
        response = requests.post(url, headers=headers, data=payload, files=files_data)
        response.raise_for_status()
        filenames = response.json().get('data', [])
        if not filenames:
            raise BadTnsRequest("Failed to upload files to TNS, please contact Hermes support")
        raw_filenames_to_tns_filenames = {}
        for i, file in enumerate(files):
            raw_filenames_to_tns_filenames[file.name] = filenames[i]
        return raw_filenames_to_tns_filenames
    except Exception:
        raise BadTnsRequest("Failed to upload files to TNS, please try again later")


def submit_classification_report_to_tns(request, classification_report):
    """ Submit a tns formatted classification report message to the tns server """
    data = {'classification_report': classification_report}
    response = submit_report_to_tns(request, data)
    if response.get('id_code', 0) != 200:
        raise BadTnsRequest(f"TNS classification submission failed. The response was: {response}")
    return response


def submit_at_report_to_tns(request, at_report):
    """ Submit a tns formatted AT report message to the tns server, and returns the TNS object names """
    data = {'at_report': at_report}
    response = submit_report_to_tns(request, data)
    object_names = []
    if isinstance(response, dict):
        object_names = parse_object_from_tns_response(response)

    if not object_names:
        raise BadTnsRequest(f"TNS submission failed to be processed within 10 seconds. The report_id = {response}")
    return object_names


def submit_report_to_tns(request, data):
    """ Submits to the TNS bulk submission API. This first submits the payload, gets a report_id, and then queries for
        that report_id to track its completion. Once completed, the response is returned, or if we time out the
        report_id is returned instead.
    """
    payload = {
        'api_key': get_tns_api_token(request),
        'data': json.dumps(data, indent=4)
    }
    url = urljoin(settings.TNS_BASE_URL, 'api/bulk-report')
    headers = {'User-Agent': get_tns_marker(request)}
    try:
        response = requests.post(url, headers = headers, data = payload)
        response.raise_for_status()
        report_id = response.json()['data']['report_id']
    except Exception:
        raise BadTnsRequest("Failed to submit report to TNS")

    attempts = 0
    reply_url = urljoin(settings.TNS_BASE_URL, 'api/bulk-report-reply')
    reply_data = {'api_key': get_tns_api_token(request), 'report_id': report_id}
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
            return response.json()
    return report_id
