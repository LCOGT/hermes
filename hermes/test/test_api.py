from django.test import TestCase
from django.core.management import call_command
from django.urls import reverse

from hermes.models import Message, NonLocalizedEvent, NonLocalizedEventSequence, Target

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
