from django.test import TestCase
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from copy import deepcopy

from hermes.models import Message, NonLocalizedEvent, Target
from hermes.serializers import HermesCandidateSerializer

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


class TestSubmitGenericMessageApi(TestCase):
    def setUp(self):
        super().setUp()
        self.generic_message = {
            'title': 'Candidate message',
            'topic': 'hermes.candidates',
            'message_text': 'This is a candidate message.',
            'submitter': 'Hermes Guest',
            'authors': 'Test Person1 <testperson1@gmail.com>, Test Person2 <testperson2@gmail.com>',
            'data': {
                'anything': 'goes',
                'in': [{
                    'here': 'or',
                    'ra': '33.2',
                    'dec': '42.2'
                }]
            }
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


class TestSubmitCandidatesApi(TestCase):
    def setUp(self):
        super().setUp()
        self.good_candidate = {
            'title': 'Candidate message',
            'topic': 'hermes.candidates',
            'message_text': 'This is a candidate message.',
            'submitter': 'Hermes Guest',
            'authors': 'Test Person1 <testperson1@gmail.com>, Test Person2 <testperson2@gmail.com>',
            'data': {
                'event_id': 'S123456',
                'candidates': [{
                    'target_name': 'm44',
                    'ra': '33.2',
                    'dec': '42.2',
                    'date': timezone.now().isoformat(),
                    'telescope': '1m0a.doma.elp.lco',
                    'instrument': 'fa16',
                    'band': 'g',
                    'brightness': 22.5,
                    'brightness_error': 1.5,
                    'brightness_unit': 'AB mag'
            }],
                'extra_data': {
                    'test_key': 'test_value'
                }
            }
        }
        # Set up the session for the middleware
        session = self.client.session
        session['user_api_token_expiration'] = (timezone.now() + timedelta(days=1)).isoformat()
        session.save()

    def test_good_candidate_submission_accepted(self):
        result = self.client.post(reverse('submit_candidates-validate'), self.good_candidate, content_type="application/json")
        self.assertEqual(result.status_code, 200)

    def test_candidate_time_mjd_submission_accepted(self):
        good_candidate = deepcopy(self.good_candidate)
        good_candidate['data']['candidates'][0]['date'] = '2348532.241'
        good_candidate['data']['candidates'][0]['date_format'] = 'mjd'
        result = self.client.post(reverse('submit_candidates-validate'), good_candidate, content_type="application/json")
        self.assertEqual(result.status_code, 200)

    def test_candidate_unknown_time_format_rejected(self):
        bad_candidate = deepcopy(self.good_candidate)
        bad_candidate['data']['candidates'][0]['date'] = '2348532.241'
        bad_candidate['data']['candidates'][0]['date_format'] = 'geo'
        result = self.client.post(reverse('submit_candidates-validate'), bad_candidate, content_type="application/json")
        self.assertContains(result, 'does not parse', status_code=200)

    def test_candidate_ha_ra_format(self):
        good_candidate = deepcopy(self.good_candidate)
        good_candidate['data']['candidates'][0]['ra'] = '23:21:16'
        result = self.client.post(reverse('submit_candidates-validate'), good_candidate, content_type="application/json")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json(), {})

        # Now check the ra is converted to decimal degrees within the validated data
        serializer = HermesCandidateSerializer(data=good_candidate)
        self.assertTrue(serializer.is_valid())
        expected_ra_deg = 350.316666666666
        self.assertAlmostEqual(serializer.validated_data['data']['candidates'][0]['ra'], expected_ra_deg)

    def test_candidate_unknown_ra_format_rejected(self):
        bad_candidate = deepcopy(self.good_candidate)
        bad_candidate['data']['candidates'][0]['ra'] = 'Ra is 5.2'
        result = self.client.post(reverse('submit_candidates-validate'), bad_candidate, content_type="application/json")
        self.assertContains(result, 'Must be in a format astropy understands', status_code=200)

    def test_candidate_ra_out_of_bounds_loops(self):
        good_candidate = deepcopy(self.good_candidate)
        expected_ra = 930.3
        good_candidate['data']['candidates'][0]['ra'] = f'{expected_ra}'
        # Now check the ra is converted to decimal degrees and looped into valid range within the validated data
        serializer = HermesCandidateSerializer(data=good_candidate)
        self.assertTrue(serializer.is_valid())
        self.assertAlmostEqual(serializer.validated_data['data']['candidates'][0]['ra'], expected_ra % 360.0)

    def test_candidate_dec_out_of_bounds_rejected(self):
        bad_candidate = deepcopy(self.good_candidate)
        bad_candidate['data']['candidates'][0]['dec'] = '930.3'
        result = self.client.post(reverse('submit_candidates-validate'), bad_candidate, content_type="application/json")
        self.assertContains(result, 'Must be in a format astropy understands', status_code=200)

    def test_only_required_fields_accepted(self):
        good_candidate = deepcopy(self.good_candidate)
        del good_candidate['authors']
        del good_candidate['data']['extra_data']
        del good_candidate['data']['candidates'][0]['brightness']
        del good_candidate['data']['candidates'][0]['brightness_error']
        del good_candidate['data']['candidates'][0]['brightness_unit']
        del good_candidate['data']['candidates'][0]['telescope']
        del good_candidate['data']['candidates'][0]['instrument']

        result = self.client.post(reverse('submit_candidates-validate'), good_candidate, content_type="application/json")
        self.assertEqual(result.status_code, 200)
    
    def test_missing_a_required_field_rejected(self):
        bad_candidate = deepcopy(self.good_candidate)
        del bad_candidate['topic']

        result = self.client.post(reverse('submit_candidates-validate'), bad_candidate, content_type="application/json")
        self.assertContains(result, 'field is required', status_code=200)
