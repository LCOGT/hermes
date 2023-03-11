from django.test import TestCase
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from copy import deepcopy
import math

from hermes.models import Message, NonLocalizedEvent, Target
from hermes.serializers import HermesMessageSerializer

class TestApiFiltering(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        # Setup some sample models
        cls.event1_id = 'S192837'
        call_command('inject_message', event_id=cls.event1_id, type='LVC_INITIAL', sequence_number=1)
        call_command('inject_message', event_id=cls.event1_id, type='LVC_PRELIMINARY', sequence_number=2)
        call_command('inject_message', event_id=cls.event1_id, type='LVC_UPDATE', sequence_number=3)
        cls.event1 = NonLocalizedEvent.objects.get(event_id=cls.event1_id)
        
        cls.event2_id = 'S735592'
        call_command('inject_message', event_id=cls.event2_id, type='LVC_INITIAL', sequence_number=1)
        call_command('inject_message', event_id=cls.event2_id, type='LVC_RETRACTION', sequence_number=2)
        cls.event2 = NonLocalizedEvent.objects.get(event_id=cls.event2_id)
        
        # Add a few counterpart messages with targets
        cls.target1_ra = 26.75
        cls.target1_dec = 76.43
        call_command('inject_message', event_id=cls.event1_id, type='LVC_COUNTERPART', source_sernum=1, target_ra=cls.target1_ra, target_dec=cls.target1_dec)
        cls.target2_ra = 14.82
        cls.target2_dec = 82.14
        call_command('inject_message', event_id=cls.event1_id, type='LVC_COUNTERPART', source_sernum=2, target_ra=cls.target2_ra, target_dec=cls.target2_dec)
        cls.target3_ra = 55.5
        cls.target3_dec = 77.7
        call_command('inject_message', event_id=cls.event2_id, type='LVC_COUNTERPART', source_sernum=1, target_ra=cls.target3_ra, target_dec=cls.target3_dec)

        # Add a few gcn circular messages that relate to the event
        call_command('inject_message', event_id=cls.event1_id, type='GCN_CIRCULAR', author='Test Author 1 <testauthor1@mail.com>')
        call_command('inject_message', event_id=cls.event1_id, type='GCN_CIRCULAR', author='Test Author 2 <testauthor2@mail.com>')

    def setUp(self):
        # Set up the session for the middleware
        session = self.client.session
        session['user_api_token_expiration'] = (timezone.now() + timedelta(days=1)).isoformat()
        session.save()

    def test_models_are_created(self):
        self.assertEquals(Message.objects.all().count(), 10)
        self.assertEquals(self.event1.sequences.count(), 3)
        self.assertEquals(self.event2.sequences.count(), 2)
        self.assertEqual(Target.objects.all().count(), 3)

    def test_filter_target_by_event(self):
        result = self.client.get(reverse('targets-list'))
        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(result.json()['results']), 3)
        result = self.client.get(reverse('targets-list') + f'?event_id={self.event1_id}')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(result.json()['results']), 2)
        result = self.client.get(reverse('targets-list') + f'?event_id={self.event2_id}')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(result.json()['results']), 1)
    
    def test_filter_target_by_cone_search(self):
        result = self.client.get(reverse('targets-list') + f'?cone_search=26,75,5')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(result.json()['results']), 1)
        target_name = self.event1_id + '_X1'
        self.assertContains(result, target_name)
        self.assertContains(result, self.target1_ra)
        self.assertContains(result, self.target1_dec)

    def test_get_events_by_id(self):
        result = self.client.get(reverse('events-detail', args=(self.event1_id,)))
        self.assertEqual(result.status_code, 200)
        self.assertContains(result, self.event1_id)
        result = self.client.get(reverse('events-detail', args=(self.event2_id,)))
        self.assertEqual(result.status_code, 200)
        self.assertContains(result, self.event2_id)
        result = self.client.get(reverse('events-detail', args=('S999999',)))
        self.assertEqual(result.status_code, 404)

    def test_get_eventsequences_by_event_id(self):
        result = self.client.get(reverse('eventsequences-list') + f'?event_id={self.event1_id}')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(result.json()['results']), 3)
        result = self.client.get(reverse('eventsequences-list') + f'?event_id={self.event2_id}')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(result.json()['results']), 2)
    
    def test_get_event_sequences_by_sequence_type(self):
        result = self.client.get(reverse('eventsequences-list') + f'?sequence_type=INITIAL')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(result.json()['results']), 2)
        result = self.client.get(reverse('eventsequences-list') + f'?sequence_type=INITIAL&sequence_type=UPDATE')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(result.json()['results']), 3)
        result = self.client.get(reverse('eventsequences-list') + f'?exclude_sequence_type=RETRACTION')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(result.json()['results']), 4)

    def test_get_messages_by_event_id(self):
        result = self.client.get(reverse('messages-list') + f'?event_id={self.event1_id}')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(result.json()['results']), 4)
        result = self.client.get(reverse('messages-list') + f'?event_id={self.event2_id}')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(result.json()['results']), 1)
    
    def test_get_messages_by_cone_search(self):
        result = self.client.get(reverse('messages-list') + f'?cone_search=13,81,3')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(result.json()['results']), 1)
        target_name = self.event1_id + '_X2'
        self.assertContains(result, target_name)
        self.assertContains(result, self.target2_ra)
        self.assertContains(result, self.target2_dec)


class TestSubmitBasicMessageApi(TestCase):
    def setUp(self):
        super().setUp()
        self.generic_message = {
            'title': 'Candidate message',
            'topic': 'hermes.candidates',
            'message_text': 'This is a candidate message.',
            'submitter': 'Hermes Guest',
            'authors': 'Test Person1 <testperson1@gmail.com>, Test Person2 <testperson2@gmail.com>',
            'data': {}
        }
        # Set up the session for the middleware
        session = self.client.session
        session['user_api_token_expiration'] = (timezone.now() + timedelta(days=1)).isoformat()
        session.save()
    
    def test_good_message_submission_accepted(self):
        result = self.client.post(reverse('submit_message-validate'), self.generic_message, content_type="application/json")
        self.assertEqual(result.status_code, 200)

    def test_good_message_submission_without_data_accepted(self):
        good_message = deepcopy(self.generic_message)
        del good_message['data']
        del good_message['authors']
        result = self.client.post(reverse('submit_message-validate'), good_message, content_type="application/json")
        self.assertEqual(result.status_code, 200)
    
    def test_message_submission_required_topic(self):
        bad_message = deepcopy(self.generic_message)
        del bad_message['topic']
        result = self.client.post(reverse('submit_message-validate'), bad_message, content_type="application/json")
        self.assertContains(result, 'field is required', status_code=200)


class TestBaseMessageApi(TestCase):
    def setUp(self):
        super().setUp()
        self.ra_target1 = {
            'name': 'test target 1',
            'ra': '33.2',
            'dec': '42.2',
        }
        self.ra_target2 = {
            'name': 'test target 2',
            'ra':  '23:21:16',
            'dec': '68.7',
        }
        self.orb_el_target1 = {
            'name': 'test orbel 1',
            'orbital_elements': {
                'epoch_of_elements': '57660.0',
                'orbital_inclination': 9.7942900,
                'longitude_of_the_ascending_node': 122.8943400,
                'argument_of_the_perihelion': 78.3278300,
                'semimajor_axis': 0.7701170,
                'mean_anomaly': 165.6860400,
                'eccentricity': 0.5391962,
            }
        }
        self.orb_el_target2 = {
            'name': 'test orbel 2',
            'orbital_elements': {
                'epoch_of_elements': '57660.0',
                'orbital_inclination': 9.7942900,
                'longitude_of_the_ascending_node': 122.8943400,
                'argument_of_the_perihelion': 78.3278300,
                'perihelion_distance': 1.0,
                'eccentricity': 0.5391962,
                'epoch_of_perihelion': '57400.0'
            }
        }
        self.photometry = {
            'target_name': 'test target 1',
            'date_obs': timezone.now().isoformat(),
            'telescope': '1m0a.doma.elp.lco',
            'instrument': 'fa16',
            'bandpass': 'g',
            'brightness': 22.5,
            'brightness_error': 1.5,
            'brightness_unit': 'AB mag'
        }
        self.spectroscopy = {
            'target_name': 'test target 1',
            'date_obs': timezone.now().isoformat(),
            'telescope': '1m0a.doma.elp.lco',
            'instrument': 'fa16',
            'flux': [2348.34],
            'flux_error': [20.6],
            'wavelength': [725.25],
            'wavelength_units': 'nm'
            
        }
        self.astrometry = {
            'target_name': 'test target 1',
            'date_obs': timezone.now().isoformat(),
            'telescope': '1m0a.doma.elp.lco',
            'instrument': 'fa16',
            'ra': '23.8',
            'dec': '31.4',
            'ra_error': 0.2,
            'ra_error_units': 'degrees',
            'dec_error': 12,
            'dec_error_units': 'arcsec'
        }
        # Set up the session for the middleware
        session = self.client.session
        session['user_api_token_expiration'] = (timezone.now() + timedelta(days=1)).isoformat()
        session.save()


class TestSubmitReferencesMessageApi(TestBaseMessageApi):
    def setUp(self):
        super().setUp()
        self.good_message = {
            'title': 'Candidate message',
            'topic': 'hermes.candidates',
            'message_text': 'This is a candidate message.',
            'submitter': 'Hermes Guest',
            'authors': 'Test Person1 <testperson1@gmail.com>, Test Person2 <testperson2@gmail.com>',
            'data': {
                'event_id': 'S123456',
                'references': [{
                    'source': 'GCN',
                    'citation': 'S123456'
                }],
                'extra_data': {
                    'test_key': 'test_value'
                }
            }
        }

    def test_good_reference_submits_successfully(self):
        good_message = deepcopy(self.good_message)
        result = self.client.post(reverse('submit_message-validate'), good_message, content_type="application/json")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json(), {})

    def test_reference_with_citation_requires_source(self):
        bad_message = deepcopy(self.good_message)
        bad_reference = {
            'citation': 'S12345',
        }
        bad_message['data']['references'] = [bad_reference]
        result = self.client.post(reverse('submit_message-validate'), bad_message, content_type="application/json")
        self.assertContains(result, 'Must set source with citation', status_code=200)

    def test_empty_reference_fails(self):
        bad_message = deepcopy(self.good_message)
        bad_message['data']['references'] = [{}]
        result = self.client.post(reverse('submit_message-validate'), bad_message, content_type="application/json")
        self.assertContains(result, 'Must set source/citation or url', status_code=200)


class TestSubmitTargetMessageApi(TestBaseMessageApi):
    def setUp(self):
        super().setUp()
        self.good_message = {
            'title': 'Candidate message',
            'topic': 'hermes.candidates',
            'message_text': 'This is a candidate message.',
            'submitter': 'Hermes Guest',
            'authors': 'Test Person1 <testperson1@gmail.com>, Test Person2 <testperson2@gmail.com>',
            'data': {
                'event_id': 'S123456',
                'references': [],
                'targets': [self.ra_target1],
                'extra_data': {
                    'test_key': 'test_value'
                }
            }
        }

    def test_good_targets_submit_successfully(self):
        good_message = deepcopy(self.good_message)
        good_message['data']['targets'] = [
            self.ra_target1, self.ra_target2, self.orb_el_target1, self.orb_el_target2
        ]
        result = self.client.post(reverse('submit_message-validate'), good_message, content_type="application/json")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json(), {})

    def test_target_requires_dec_if_ra_is_set(self):
        bad_message = deepcopy(self.good_message)
        bad_target = {
            'name': 'test target',
            'ra': '12.2'
        }
        bad_message['data']['targets'] = [bad_target]
        result = self.client.post(reverse('submit_message-validate'), bad_message, content_type="application/json")
        self.assertContains(result, 'Must set dec if ra is set', status_code=200)

    def test_target_requires_ra_if_dec_is_set(self):
        bad_message = deepcopy(self.good_message)
        bad_target = {
            'name': 'test target',
            'dec': '12.2'
        }
        bad_message['data']['targets'] = [bad_target]
        result = self.client.post(reverse('submit_message-validate'), bad_message, content_type="application/json")
        self.assertContains(result, 'Must set ra if dec is set', status_code=200)

    def test_target_requires_ra_dec_or_orbital_elements(self):
        bad_message = deepcopy(self.good_message)
        bad_target = {
            'name': 'test target',
        }
        bad_message['data']['targets'] = [bad_target]
        result = self.client.post(reverse('submit_message-validate'), bad_message, content_type="application/json")
        self.assertContains(result, 'ra/dec or orbital elements are required', status_code=200)

    def test_orbital_element_target_requires_means_or_peris(self):
        bad_message = deepcopy(self.good_message)
        bad_target = {
            'name': 'test target',
            'orbital_elements': {
                'epoch_of_elements': '57660.0',
                'orbital_inclination': 9.7942900,
                'longitude_of_the_ascending_node': 122.8943400,
                'argument_of_the_perihelion': 78.3278300,
                'eccentricity': 0.5391962,
            }
        }
        bad_message['data']['targets'] = [bad_target]
        result = self.client.post(reverse('submit_message-validate'), bad_message, content_type="application/json")
        self.assertContains(result, 'Must set mean_anomaly/semimajor_axis or epoch_of_perihelion/perihelion_distance', status_code=200)

    def test_orbital_element_target_semimajor_axis_requires_mean_anomaly(self):
        bad_message = deepcopy(self.good_message)
        bad_target = {
            'name': 'test target',
            'orbital_elements': {
                'epoch_of_elements': '57660.0',
                'orbital_inclination': 9.7942900,
                'longitude_of_the_ascending_node': 122.8943400,
                'argument_of_the_perihelion': 78.3278300,
                'eccentricity': 0.5391962,
                'semimajor_axis': 100.0
            }
        }
        bad_message['data']['targets'] = [bad_target]
        result = self.client.post(reverse('submit_message-validate'), bad_message, content_type="application/json")
        self.assertContains(result, 'Must set mean_anomaly when semimajor_axis is set', status_code=200)

    def test_orbital_element_target_perihelion_distance_requires_epoch_of_perihelion(self):
        bad_message = deepcopy(self.good_message)
        bad_target = {
            'name': 'test target',
            'orbital_elements': {
                'epoch_of_elements': '57660.0',
                'orbital_inclination': 9.7942900,
                'longitude_of_the_ascending_node': 122.8943400,
                'argument_of_the_perihelion': 78.3278300,
                'eccentricity': 0.5391962,
                'perihelion_distance': 100.0
            }
        }
        bad_message['data']['targets'] = [bad_target]
        result = self.client.post(reverse('submit_message-validate'), bad_message, content_type="application/json")
        self.assertContains(result, 'Must set epoch_of_perihelion when perihelion_distance is set', status_code=200)

    def test_orbital_elements_requires_a_set_of_fields(self):
        good_message = deepcopy(self.good_message)
        good_message['data']['targets'][0]['orbital_elements'] = {}
        result = self.client.post(reverse('submit_message-validate'), good_message, content_type="application/json")
        self.assertContains(result, 'This field is required', status_code=200)
        missing_fields = result.json()['data']['targets'][0]['orbital_elements'].keys()
        required_fields = ['epoch_of_elements', 'orbital_inclination', 'longitude_of_the_ascending_node',
                           'argument_of_the_perihelion', 'eccentricity']
        for field in required_fields:
            self.assertIn(field, missing_fields)

    def test_message_ha_ra_format(self):
        good_message = deepcopy(self.good_message)
        good_message['data']['targets'][0]['ra'] = '23:21:16'
        result = self.client.post(reverse('submit_message-validate'), good_message, content_type="application/json")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json(), {})

        # Now check the ra is converted to decimal degrees within the validated data
        serializer = HermesMessageSerializer(data=good_message)
        self.assertTrue(serializer.is_valid())
        expected_ra_deg = 350.316666666666
        self.assertAlmostEqual(serializer.validated_data['data']['targets'][0]['ra'], expected_ra_deg)

    def test_message_unknown_ra_format_rejected(self):
        bad_message = deepcopy(self.good_message)
        bad_message['data']['targets'][0]['ra'] = 'Ra is 5.2'
        result = self.client.post(reverse('submit_message-validate'), bad_message, content_type="application/json")
        self.assertContains(result, 'Must be in a format astropy understands', status_code=200)

    def test_message_ra_out_of_bounds_loops(self):
        good_message = deepcopy(self.good_message)
        expected_ra = 930.3
        good_message['data']['targets'][0]['ra'] = f'{expected_ra}'
        # Now check the ra is converted to decimal degrees and looped into valid range within the validated data
        serializer = HermesMessageSerializer(data=good_message)
        self.assertTrue(serializer.is_valid())
        self.assertAlmostEqual(serializer.validated_data['data']['targets'][0]['ra'], expected_ra % 360.0)

    def test_message_dec_out_of_bounds_rejected(self):
        bad_message = deepcopy(self.good_message)
        bad_message['data']['targets'][0]['dec'] = '930.3'
        result = self.client.post(reverse('submit_message-validate'), bad_message, content_type="application/json")
        self.assertContains(result, 'Must be in a format astropy understands', status_code=200)

    def test_message_ra_nan_rejected(self):
        bad_message = deepcopy(self.good_message)
        bad_message['data']['targets'][0]['ra'] = 'NaN'
        result = self.client.post(reverse('submit_message-validate'), bad_message, content_type="application/json")
        self.assertContains(result, 'Value must be finite', status_code=200)


class TestSubmitPhotometryMessageApi(TestBaseMessageApi):
    def setUp(self):
        super().setUp()
        self.good_message = {
            'title': 'Candidate FloatField',
            'topic': 'hermes.candidates',
            'message_text': 'This is a candidate message.',
            'submitter': 'Hermes Guest',
            'authors': 'Test Person1 <testperson1@gmail.com>, Test Person2 <testperson2@gmail.com>',
            'data': {
                'event_id': 'S123456',
                'references': [],
                'targets': [self.ra_target1],
                'photometry': [self.photometry],
                'extra_data': {
                    'test_key': 'test_value'
                }
            }
        }

    def test_good_message_submission_accepted(self):
        result = self.client.post(reverse('submit_message-validate'), self.good_message, content_type="application/json")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json(), {})

    def test_message_time_mjd_submission_accepted(self):
        good_message = deepcopy(self.good_message)
        good_message['data']['photometry'][0]['date_obs'] = '2348532.241'
        result = self.client.post(reverse('submit_message-validate'), good_message, content_type="application/json")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json(), {})

    def test_message_unknown_time_format_rejected(self):
        bad_message = deepcopy(self.good_message)
        bad_message['data']['photometry'][0]['date_obs'] = '23-not-valid-date:22.2'
        result = self.client.post(reverse('submit_message-validate'), bad_message, content_type="application/json")
        self.assertContains(result, 'does not parse', status_code=200)

    def test_message_brightness_error_nan_rejected(self):
        bad_message = deepcopy(self.good_message)
        bad_message['data']['photometry'][0]['brightness'] = math.nan
        result = self.client.post(reverse('submit_message-validate'), bad_message, content_type="application/json")
        self.assertContains(result, 'JSON parse error', status_code=400)

    def test_message_brightness_inf_rejected(self):
        bad_message = deepcopy(self.good_message)
        bad_message['data']['photometry'][0]['brightness'] = math.inf
        result = self.client.post(reverse('submit_message-validate'), bad_message, content_type="application/json")
        self.assertContains(result, 'JSON parse error', status_code=400)

    def test_message_telescope_or_instrument_required(self):
        bad_message = deepcopy(self.good_message)
        del bad_message['data']['photometry'][0]['telescope']
        bad_message['data']['photometry'][0]['instrument'] = ''
        result = self.client.post(reverse('submit_message-validate'), bad_message, content_type="application/json")
        self.assertContains(result, 'Must have at least one of telescope or instrument set', status_code=200)

    def test_only_required_photometry_fields_accepted(self):
        good_message = deepcopy(self.good_message)
        del good_message['authors']
        del good_message['data']['extra_data']
        del good_message['data']['photometry'][0]['brightness_error']
        del good_message['data']['photometry'][0]['brightness_unit']
        del good_message['data']['photometry'][0]['instrument']

        result = self.client.post(reverse('submit_message-validate'), good_message, content_type="application/json")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json(), {})

    def test_target_name_doesnt_match_rejected(self):
        bad_message = deepcopy(self.good_message)
        bad_message['data']['photometry'][0]['target_name'] = 'not-present'
        result = self.client.post(reverse('submit_message-validate'), bad_message, content_type="application/json")
        self.assertContains(result, 'The target_name must reference a name in your target table', status_code=200)

    def test_no_target_table_rejected(self):
        bad_message = deepcopy(self.good_message)
        del bad_message['data']['targets']
        result = self.client.post(reverse('submit_message-validate'), bad_message, content_type="application/json")
        self.assertContains(result, 'The target_name must reference a name in your target table', status_code=200)

    def test_multiple_targets_present(self):
        good_message = deepcopy(self.good_message)
        target2 = deepcopy(good_message['data']['targets'][0])
        target2['ra'] = '36.7'
        target2['name'] = 'm55'
        target2['dec'] = '67.8'
        good_message['data']['targets'].append(target2)
        good_message['data']['photometry'].append(deepcopy(good_message['data']['photometry'][0]))
        good_message['data']['photometry'][1]['target_name'] = 'm55'

        result = self.client.post(reverse('submit_message-validate'), good_message, content_type="application/json")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json(), {})

    def test_basic_fields_are_required(self):
        required_fields = ['bandpass', 'target_name']
        bad_message = deepcopy(self.good_message)
        bad_message['data']['photometry'][0] = {}
        result = self.client.post(reverse('submit_message-validate'), bad_message, content_type="application/json")
        self.assertContains(result, 'This field is required', status_code=200)
        missing_fields = result.json()['data']['photometry'][0].keys()
        for field in required_fields:
            self.assertIn(field, missing_fields)

    def test_requires_brightness_or_limiting_brightness(self):
        bad_message = deepcopy(self.good_message)
        del bad_message['data']['photometry'][0]['brightness']
        result = self.client.post(reverse('submit_message-validate'), bad_message, content_type="application/json")
        self.assertContains(result, 'brightness or limiting_brightness are required', status_code=200)

    def test_limiting_brightness_only_succeeds(self):
        good_message = deepcopy(self.good_message)
        good_message['data']['photometry'][0]['limiting_brightness'] = 33.3
        good_message['data']['photometry'][0]['limiting_brightness_unit'] = "erg / s / cm² / Å"
        del good_message['data']['photometry'][0]['brightness_error']
        del good_message['data']['photometry'][0]['brightness_unit']
        del good_message['data']['photometry'][0]['brightness']

        result = self.client.post(reverse('submit_message-validate'), good_message, content_type="application/json")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json(), {})


class TestSubmitSpectroscopyMessageApi(TestBaseMessageApi):
    def setUp(self):
        super().setUp()
        self.good_message = {
            'title': 'Candidate message',
            'topic': 'hermes.candidates',
            'message_text': 'This is a candidate message.',
            'submitter': 'Hermes Guest',
            'authors': 'Test Person1 <testperson1@gmail.com>, Test Person2 <testperson2@gmail.com>',
            'data': {
                'event_id': 'S123456',
                'references': [],
                'targets': [self.ra_target1],
                'spectroscopy': [self.spectroscopy],
                'extra_data': {
                    'test_key': 'test_value'
                }
            }
        }

    def test_good_spectroscopy_section_submits_ok(self):
        result = self.client.post(reverse('submit_message-validate'), self.good_message, content_type="application/json")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json(), {})

    def test_spectroscopy_requires_flux_and_wavelength(self):
        bad_message = deepcopy(self.good_message)
        del bad_message['data']['spectroscopy'][0]['flux']
        del bad_message['data']['spectroscopy'][0]['wavelength']
        result = self.client.post(reverse('submit_message-validate'), bad_message, content_type="application/json")
        self.assertContains(result, 'flux', status_code=200)
        self.assertContains(result, 'wavelength', status_code=200)

    def test_spectroscopy_flux_and_wavelength_list_sizes_must_match(self):
        bad_message = deepcopy(self.good_message)
        bad_message['data']['spectroscopy'][0]['flux'] = [1, 2, 3]
        result = self.client.post(reverse('submit_message-validate'), bad_message, content_type="application/json")
        self.assertContains(result, 'Must have same number of datapoints for flux and flux_error', status_code=200)
