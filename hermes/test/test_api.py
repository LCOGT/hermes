from django.test import TestCase
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth.models import User
from rest_framework.response import Response
from datetime import timedelta
from copy import deepcopy
import math
from unittest.mock import patch, ANY
from hermes.models import Message, NonLocalizedEvent, Target, Profile
from hermes.serializers import HermesMessageSerializer
from hermes.test.test_tns import populate_test_tns_options
from hop.io import Producer


class TestApiFiltering(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        # Setup some sample models
        cls.event1_id = 'S192837'
        call_command('inject_message', event_id=cls.event1_id, type='LVC_INITIAL', sequence_number=1, skymap_version=0)
        call_command('inject_message', event_id=cls.event1_id, type='LVC_PRELIMINARY', sequence_number=2, skymap_version=1)
        call_command('inject_message', event_id=cls.event1_id, type='LVC_UPDATE', sequence_number=3, skymap_version=1)
        cls.event1 = NonLocalizedEvent.objects.get(event_id=cls.event1_id)
        
        cls.event2_id = 'S735592'
        call_command('inject_message', event_id=cls.event2_id, type='LVC_INITIAL', sequence_number=1, skymap_version=0)
        call_command('inject_message', event_id=cls.event2_id, type='LVC_RETRACTION', sequence_number=2, skymap_version=-1)
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

    def test_get_messages_by_search_event_id(self):
        result = self.client.get(reverse('messages-list') + f'?search={self.event2_id}')
        self.assertEqual(result.status_code, 200)
        # Two from the event and 1 from a counterpart message on that event
        self.assertEqual(len(result.json()['results']), 3)

    def test_get_messages_by_search_topic(self):
        result = self.client.get(reverse('messages-list') + '?search=COUNTERPART')
        self.assertEqual(result.status_code, 200)
        # 3 from counterpart notices, 2 from subject line of gcn circulars
        self.assertEqual(len(result.json()['results']), 5)

    def test_get_messages_by_search_multiple_or(self):
        result = self.client.get(reverse('messages-list') + '?search=CIRCULAR COUNTERPART')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(result.json()['results']), 5)

    def test_get_messages_by_search_quoted_string_together(self):
        result = self.client.get(reverse('messages-list') + '?search="GCN CIRCULAR"')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(result.json()['results']), 2)
        result = self.client.get(reverse('messages-list') + '?search=GCN CIRCULAR')
        self.assertEqual(result.status_code, 200)
        # All 10 test messages have either GCN or CIRCULAR in them
        self.assertEqual(len(result.json()['results']), 5)


class TestSubmitBasicMessageApi(TestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create(username='testuser')
        self.profile = Profile.objects.create(
            user=self.user, credential_name='abc', credential_password='abc'
        )
        self.generic_message = {
            'title': 'Candidate message',
            'topic': 'hermes.test',
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

    @patch('hermes.views.submit_to_hop')
    def test_arbitrary_fields_are_accepted(self, mock_submit):
        self.client.force_login(self.user)
        mock_submit.return_value = Response({"message": "Message was submitted successfully."}, status=200)
        good_message = deepcopy(self.generic_message)
        good_message['data'] = {
            'test_string': 'test_value_1',
            'test_float': 245.55,
            'test_array': ['this', 'is', 'an', 'array'],
            'test_object': {'test_key1': 'test_value', 'test_key2': 22.3}
        }
        result = self.client.post(reverse('submit_message-list'), good_message, content_type="application/json")
        self.assertEqual(result.status_code, 200)
        metadata = {'topic': good_message['topic']}
        payload, _ = Producer.pack(good_message, metadata)
        mock_submit.assert_called_with(ANY, payload, ANY, ANY)

    @patch('hermes.views.submit_to_hop')
    def test_submit_to_flags_are_removed(self, mock_submit):
        self.client.force_login(self.user)
        mock_submit.return_value = Response({"message": "Message was submitted successfully."}, status=200)
        good_message = deepcopy(self.generic_message)
        good_message['submit_to_tns'] = False
        good_message['submit_to_mpc'] = False
        result = self.client.post(reverse('submit_message-list'), good_message, content_type="application/json")
        self.assertEqual(result.status_code, 200)
        del good_message['submit_to_tns']
        del good_message['submit_to_mpc']
        metadata = {'topic': good_message['topic']}
        payload, _ = Producer.pack(good_message, metadata)
        mock_submit.assert_called_with(ANY, payload, ANY, ANY)


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
        self.limiting_photometry = {
            'target_name': 'test target 1',
            'date_obs': (timezone.now() - timedelta(days=7)).isoformat(),
            'telescope': '1m0a.doma.elp.lco',
            'instrument': 'fa16',
            'bandpass': 'g',
            'limiting_brightness': 20.2,
            'limiting_brightness_error': 0.5,
            'limiting_brightness_unit': 'AB mag'
        }
        self.spectroscopy = {
            'target_name': 'test target 1',
            'date_obs': timezone.now().isoformat(),
            'telescope': '1m0a.doma.elp.lco',
            'instrument': 'fa16',
            'flux': [2348.34],
            'flux_error': [20.6],
            'wavelength': [725.25],
            'wavelength_units': 'nm',
            'observer': 'observer1',
            'reducer': 'reducer1',
            'spec_type': 'Sky'
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
            'topic': 'hermes.test',
            'message_text': 'This is a candidate message.',
            'submitter': 'Hermes Guest',
            'authors': 'Test Person1 <testperson1@gmail.com>, Test Person2 <testperson2@gmail.com>',
            'data': {
                'event_id': 'S123456',
                'references': [{
                    'source': 'GCN',
                    'citation': 'S123456'
                }],
                'test_key': 'test_value'
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
            'topic': 'hermes.test',
            'message_text': 'This is a candidate message.',
            'submitter': 'Hermes Guest',
            'authors': 'Test Person1 <testperson1@gmail.com>, Test Person2 <testperson2@gmail.com>',
            'data': {
                'event_id': 'S123456',
                'references': [],
                'targets': [self.ra_target1],
                'test_key': 'test_value'
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

    def test_none_optional_field_accepted(self):
        good_message = deepcopy(self.good_message)
        good_message['data']['targets'][0]['pm_ra'] = None
        result = self.client.post(reverse('submit_message-validate'), good_message, content_type="application/json")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json(), {})

    def test_aliases_list_accepted(self):
        good_message = deepcopy(self.good_message)
        good_message['data']['targets'][0]['aliases'] = [
            'special_target1',
            'my favorite target',
            'xb22021'
        ]
        result = self.client.post(reverse('submit_message-validate'), good_message, content_type="application/json")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json(), {})


class TestSubmitPhotometryMessageApi(TestBaseMessageApi):
    def setUp(self):
        super().setUp()
        self.good_message = {
            'title': 'Candidate FloatField',
            'topic': 'hermes.test',
            'message_text': 'This is a candidate message.',
            'submitter': 'Hermes Guest',
            'authors': 'Test Person1 <testperson1@gmail.com>, Test Person2 <testperson2@gmail.com>',
            'data': {
                'event_id': 'S123456',
                'references': [],
                'targets': [self.ra_target1],
                'photometry': [self.photometry],
                'test_key': 'test_value'
            }
        }

    def test_good_message_submission_accepted(self):
        result = self.client.post(reverse('submit_message-validate'), self.good_message, content_type="application/json")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json(), {})

    def test_message_time_mjd_submission_accepted(self):
        good_message = deepcopy(self.good_message)
        good_message['data']['photometry'][0]['date_obs'] = 2440532.241
        result = self.client.post(reverse('submit_message-validate'), good_message, content_type="application/json")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json(), {})

    def test_message_unknown_time_format_rejected(self):
        bad_message = deepcopy(self.good_message)
        bad_message['data']['photometry'][0]['date_obs'] = '23-not-valid-date:22.2'
        result = self.client.post(reverse('submit_message-validate'), bad_message, content_type="application/json")
        self.assertContains(result, 'does not parse', status_code=200)

    def test_message_out_of_bounds_jd_rejected(self):
        bad_message = deepcopy(self.good_message)
        bad_message['data']['photometry'][0]['date_obs'] = 24453250.241
        result = self.client.post(reverse('submit_message-validate'), bad_message, content_type="application/json")
        self.assertContains(result, 'within bounds of 2400000 to 2600000', status_code=200)

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
        del good_message['data']['test_key']
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
            'topic': 'hermes.test',
            'message_text': 'This is a candidate message.',
            'submitter': 'Hermes Guest',
            'authors': 'Test Person1 <testperson1@gmail.com>, Test Person2 <testperson2@gmail.com>',
            'data': {
                'event_id': 'S123456',
                'references': [],
                'targets': [self.ra_target1],
                'spectroscopy': [self.spectroscopy],
                'test_key': 'test_value'
            }
        }

    def test_good_spectroscopy_section_submits_ok(self):
        result = self.client.post(reverse('submit_message-validate'), self.good_message, content_type="application/json")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json(), {})

    def test_spectroscopy_requires_flux_and_wavelength_or_file(self):
        bad_message = deepcopy(self.good_message)
        del bad_message['data']['spectroscopy'][0]['flux']
        del bad_message['data']['spectroscopy'][0]['wavelength']
        result = self.client.post(reverse('submit_message-validate'), bad_message, content_type="application/json")
        self.assertContains(result, 'Must specify a spectroscopy file to upload or specify one or more flux values',
                            status_code=200)

    def test_spectroscopy_accepts_files(self):
        good_message = deepcopy(self.good_message)
        del good_message['data']['spectroscopy'][0]['flux']
        del good_message['data']['spectroscopy'][0]['wavelength']
        good_message['data']['spectroscopy'][0]['files'] = [
            {
                'name': 'MyFile1.fits',
                'description': 'This is my first spectrum file.',
                'url': 'http://myserver.org/mypath/MyFile1.fits'
            }
        ]
        result = self.client.post(reverse('submit_message-validate'), self.good_message, content_type="application/json")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json(), {})

    def test_spectroscopy_flux_and_wavelength_list_sizes_must_match(self):
        bad_message = deepcopy(self.good_message)
        bad_message['data']['spectroscopy'][0]['flux'] = [1, 2, 3]
        result = self.client.post(reverse('submit_message-validate'), bad_message, content_type="application/json")
        self.assertContains(result, 'Must have same number of datapoints for flux and flux_error', status_code=200)


@patch('hermes.tns.populate_tns_values', return_value=populate_test_tns_options())
class TestTNSSubmission(TestBaseMessageApi):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create(username='testuser')
        self.basic_message = {
            'title': 'Candidate message',
            'topic': 'hermes.test',
            'message_text': 'This is a candidate message.',
            'submitter': 'Hermes Guest',
            'submit_to_tns': True,
            'authors': 'Test Person1 <testperson1@gmail.com>, Test Person2 <testperson2@gmail.com>',
            'data': {
                'event_id': 'S123456',
                'references': [],
                'targets': [self.ra_target1],
                'photometry': [self.photometry, self.limiting_photometry],
                'test_key': 'test_value'
            }
        }
        self.client.force_login(self.user)
    
    def test_submission_requires_discovery_info(self, mock_populate_tns):
        bad_message = deepcopy(self.basic_message)
        result = self.client.post(reverse('submit_message-validate'), bad_message, content_type="application/json")
        self.assertContains(result, 'Target must have discovery info', status_code=200)

    def test_good_tns_submission(self, mock_populate_tns):
        self.client.force_login(self.user)
        good_message = deepcopy(self.basic_message)
        good_message['data']['targets'][0]['new_discovery'] = True
        good_message['data']['targets'][0]['discovery_info'] = {
            'reporting_group': 'SNEX',
            'discovery_source': 'LCO Floyds'
        }
        result = self.client.post(reverse('submit_message-validate'), good_message, content_type="application/json")
        self.assertEqual(result.json(), {})

    def test_must_be_logged_in_for_tns_submission(self, mock_populate_tns):
        self.client.logout()
        good_message = deepcopy(self.basic_message)
        good_message['data']['targets'][0]['new_discovery'] = True
        good_message['data']['targets'][0]['discovery_info'] = {
            'reporting_group': 'SNEX',
            'discovery_source': 'LCO Floyds'
        }
        result = self.client.post(reverse('submit_message-validate'), good_message, content_type="application/json")
        self.assertContains(result, 'Must be an authenticated user to submit to TNS', status_code=200)

    def test_submission_validates_group_associations_from_list(self, mock_populate_tns):
        bad_message = deepcopy(self.basic_message)
        bad_message['data']['targets'][0]['group_associations'] = [
            'SNEX',
            'NotAGroup',
            'LCO Floyds'
        ]
        result = self.client.post(reverse('submit_message-validate'), bad_message, content_type="application/json")
        self.assertContains(result, 'Group associations NotAGroup are not valid TNS groups', status_code=200)

    def test_submission_validates_fields_from_tns_options(self, mock_populate_tns):
        bad_message = deepcopy(self.basic_message)
        bad_message['data']['targets'][0]['discovery_info'] = {
            'reporting_group': 'Notagroup',
            'discovery_source': 'Also Notagroup',
            'nondetection_source': 'NotAnArchive'
        }
        bad_message['data']['photometry'][0]['bandpass'] = 'NotAFilter'
        bad_message['data']['photometry'][0]['telescope'] = 'NotATelescope'
        bad_message['data']['photometry'][0]['instrument'] = 'NotAnInstrument'

        result = self.client.post(reverse('submit_message-validate'), bad_message, content_type="application/json")
        self.assertContains(result, 'Discovery nondetection source NotAnArchive is not a valid TNS archive', status_code=200)
        self.assertContains(result, 'Discovery reporting group Notagroup is not a valid TNS group', status_code=200)
        self.assertContains(result, 'Discovery source group Also Notagroup is not a valid TNS group', status_code=200)
        self.assertContains(result, 'Bandpass NotAFilter is not a valid TNS filter', status_code=200)
        self.assertContains(result, 'Telescope NotATelescope is not a valid TNS telescope', status_code=200)
        self.assertContains(result, 'Instrument NotAnInstrument is not a valid TNS instrument', status_code=200)

    def test_submission_requires_at_least_one_target_photometry_spectroscopy(self, mock_populate_tns):
        bad_message = deepcopy(self.basic_message)
        del bad_message['data']['targets']
        del bad_message['data']['photometry']
        result = self.client.post(reverse('submit_message-validate'), bad_message, content_type="application/json")
        self.assertContains(result, 'Must fill in at least one target entry for TNS submission', status_code=200)
        self.assertContains(result,
            'Should either fill in photometry (new discovery) or spectroscopy (classification) for TNS submission',
            status_code=200
        )

    def test_submission_requires_at_least_one_photometry_nondetection(self, mock_populate_tns):
        bad_message = deepcopy(self.basic_message)
        del bad_message['data']['photometry'][1]
        result = self.client.post(reverse('submit_message-validate'), bad_message, content_type="application/json")
        self.assertContains(result, 'At least one photometry nondetection / limiting_brightness or target discovery nondetection_source must be specified for TNS submission', status_code=200)

    def test_submission_accepts_nondetection_source(self, mock_populate_tns):
        good_message = deepcopy(self.basic_message)
        good_message['data']['targets'][0]['new_discovery'] = True
        good_message['data']['targets'][0]['discovery_info'] = {
            'reporting_group': 'SNEX',
            'discovery_source': 'LCO Floyds',
            'nondetection_source': 'DSS'
        }
        del good_message['data']['photometry'][1]
        result = self.client.post(reverse('submit_message-validate'), good_message, content_type="application/json")
        self.assertEqual(result.json(), {})

    def test_submission_requires_at_least_one_photometry_detection(self, mock_populate_tns):
        bad_message = deepcopy(self.basic_message)
        del bad_message['data']['photometry'][0]
        result = self.client.post(reverse('submit_message-validate'), bad_message, content_type="application/json")
        self.assertContains(result, 'At least one photometry detection / brightness must be specified for TNS submission', status_code=200)

    def test_submission_requires_ra_dec_targets_only(self, mock_populate_tns):
        bad_message = deepcopy(self.basic_message)
        bad_message['data']['targets'][0]['discovery_info'] = {
            'reporting_group': 'SNEX',
            'discovery_source': 'LCO Floyds'
        }
        bad_message['data']['targets'].append(self.orb_el_target1)
        result = self.client.post(reverse('submit_message-validate'), bad_message, content_type="application/json")
        self.assertContains(result, 'Target ra must be present for TNS submission', status_code=200)
        self.assertContains(result, 'Target dec must be present for TNS submission', status_code=200)

    def test_submission_can_have_either_spectroscopy_or_photometry_not_both(self, mock_populate_tns):
        bad_message = deepcopy(self.basic_message)
        bad_message['data']['spectroscopy'] = [deepcopy(self.spectroscopy)]
        result = self.client.post(reverse('submit_message-validate'), bad_message, content_type="application/json")
        self.assertContains(result,
            'Should either fill in photometry (new discovery) or spectroscopy (classification) for TNS submission',
            status_code=200
        )

    def test_submission_with_spectroscopy_requires_less_target_fields(self, mock_populate_tns):
        good_message = deepcopy(self.basic_message)
        good_message['data']['spectroscopy'] = [deepcopy(self.spectroscopy)]
        del good_message['data']['photometry']
        good_message['data']['spectroscopy'][0]['classification'] = 'SN Ic'
        good_message['data']['spectroscopy'][0]['file_info'] = [{
            'name': 'test.ascii',
            'description': 'This is my spectrum'
        }]
        good_message['data']['targets'][0]['new_discovery'] = False
        good_message['data']['targets'][0]['discovery_info'] = {
            'reporting_group': 'SNEX',
        }
        result = self.client.post(reverse('submit_message-validate'), good_message, content_type="application/json")
        self.assertEqual(result.json(), {})

    def test_submission_requires_spectroscopy_fields(self, mock_populate_tns):
        bad_message = deepcopy(self.basic_message)
        bad_message['data']['spectroscopy'] = [deepcopy(self.spectroscopy)]
        del bad_message['data']['photometry']
        del bad_message['data']['spectroscopy'][0]['observer']
        del bad_message['data']['spectroscopy'][0]['reducer']
        bad_message['data']['spectroscopy'][0]['instrument'] = 'Not a Valid Instrument'
        bad_message['data']['spectroscopy'][0]['classification'] = 'Not a TNS Type'
        del bad_message['data']['spectroscopy'][0]['spec_type']
        result = self.client.post(reverse('submit_message-validate'), bad_message, content_type="application/json")
        self.assertContains(result,
            'Instrument Not a Valid Instrument is not a valid TNS instrument',
            status_code=200
        )
        self.assertContains(result,
            'Must specify a .ascii or .txt spectrum file for each spectrum in a TNS classification submission',
            status_code=200
        )
        self.assertContains(result, 'Spectroscopy must have observer specified for TNS submission', status_code=200)
        self.assertContains(result,
            'Classification Not a TNS Type is not a valid TNS classification object_type',
            status_code=200
        )
        self.assertContains(result, 'Spectroscopy must have spec_type specified for TNS submission', status_code=200)

    def test_group_associations_list_accepted(self, mock_populate_tns):
        good_message = deepcopy(self.basic_message)
        good_message['data']['targets'][0]['new_discovery'] = True
        good_message['data']['targets'][0]['discovery_info'] = {
            'reporting_group': 'SNEX',
            'discovery_source': 'LCO Floyds'
        }
        good_message['data']['targets'][0]['group_associations'] = [
            'SNEX',
            'LCO',
            'LCO Floyds'
        ]
        result = self.client.post(reverse('submit_message-validate'), good_message, content_type="application/json")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json(), {})
