from django.test import TestCase
from django.conf import settings
from django.utils import timezone
from unittest.mock import patch, ANY

from hermes.tns import reverse_tns_values, convert_discovery_hermes_message_to_tns, parse_date

import json
import os
from datetime import timedelta


def populate_test_tns_options():
    with open(os.path.join(settings.BASE_DIR, 'hermes/test/tns_options.json'), 'r') as fp:
        tns_options = json.load(fp)
        reverse_tns_options = reverse_tns_values(tns_options)
        return tns_options, reverse_tns_options


@patch('hermes.tns.populate_tns_values', return_value=populate_test_tns_options())
class TestTNS(TestCase):
    def setUp(self) -> None:
        self.maxDiff = None
        super().setUp()
        self.hermes_message = {
            'title': 'Test TNS submission message',
            'topic': 'hermes.test',
            'message_text': 'This isnt used by TNS.',
            'submitter': 'Hermes Guest',
            'submit_to_tns': True,
            'authors': 'Test Person1 <testperson1@gmail.com>, Test Person2 <testperson2@gmail.com>',
            'data': {
                'event_id': 'S123456',
                'references': [],
                'targets': [{
                    'name': 'test target 1',
                    'ra': '33.2',
                    'dec': '42.2',
                    'group_associations': [
                        'SNEX', 'LCO', 'LCO Floyds'
                    ],
                    'discovery_info': {
                        'discovery_source': 'LCO Floyds',
                        'reporting_group': 'SNEX',
                        'transient_type': 'PSN - Possible SN',
                        'proprietary_period': 1,
                        'proprietary_period_units': 'years'
                    },
                    'comments': 'This is a candidate message.',
                    'host_name': 'm33',
                    'host_redshift': 23,
                    'redshift': 17
                }],
                'photometry': [{
                    'target_name': 'test target 1',
                    'date_obs': timezone.now().isoformat(),
                    'telescope': '1m0a.doma.elp.lco',
                    'instrument': 'fa16',
                    'bandpass': 'g',
                    'brightness': 22.5,
                    'brightness_error': 1.5,
                    'brightness_unit': 'AB mag',
                    'exposure_time': 24.7,
                    'observer': 'Curtis',
                    'comments': 'Really nice discovery!'
                },
                {
                    'target_name': 'test target 1',
                    'date_obs': (timezone.now() - timedelta(days=11)).isoformat(),
                    'telescope': '1m0a.doma.elp.lco',
                    'instrument': 'fa16',
                    'bandpass': 'g',
                    'limiting_brightness': 25.0,
                    'limiting_brightness_error': 0.5,
                    'limiting_brightness_unit': 'AB mag',
                    'observer': 'Lindy',
                    'exposure_time': 540,
                    'comments': 'This nondection occured 11 days ago from LCO telescopes.'
                }],
                'test_key': 'test_value'
            }
        }

    def test_tns_conversion(self, mock_populate_tns):
        tns_message = convert_discovery_hermes_message_to_tns(self.hermes_message, filenames_mapping={})
        expected_tns_message = {'0': {'at_type': '1',
       'dec': {'error': None, 'units': None, 'value': '42.2'},
       'discovery_data_source_id': '5',
       'discovery_datetime': parse_date(self.hermes_message['data']['photometry'][0]['date_obs']).strftime('%Y-%m-%d %H:%M:%S'),
       'host_name': 'm33',
       'host_redshift': 23,
       'internal_name': 'test target 1',
       'non_detection': {'archival_remarks': '',
                         'archiveid': '',
                         'comments': 'This nondection occured 11 days ago from '
                                     'LCO telescopes.',
                         'exptime': '540',
                         'filter_value': '5',
                         'flux_units': '1',
                         'instrument_value': '236',
                         'limiting_flux': 25.0,
                         'obsdate': parse_date(self.hermes_message['data']['photometry'][1]['date_obs']).strftime('%Y-%m-%d %H:%M:%S'),
                         'observer': 'Lindy'},
       'photometry': {'photometry_group': {'0': {'comments': 'Really nice '
                                                             'discovery!',
                                                 'exptime': '24.7',
                                                 'filter_value': '5',
                                                 'flux': 22.5,
                                                 'flux_error': 1.5,
                                                 'flux_units': '1',
                                                 'instrument_value': '236',
                                                 'limiting_flux': '',
                                                 'obsdate': parse_date(self.hermes_message['data']['photometry'][0]['date_obs']).strftime('%Y-%m-%d %H:%M:%S'),
                                                 'observer': 'Curtis'}}},
       'proprietary_period': {'proprietary_period_units': 'years',
                              'proprietary_period_value': '1'},
       'proprietary_period_groups': ['1', '2', '5'],
       'ra': {'error': None, 'units': None, 'value': '33.2'},
       'related_files': {},
       'remarks': 'This is a candidate message.',
       'reporter': 'Test Person1 <testperson1@gmail.com>, Test Person2 '
                   '<testperson2@gmail.com>',
       'reporting_group_id': '1',
       'transient_redshift': 17}}

        self.assertDictEqual(tns_message, expected_tns_message)
