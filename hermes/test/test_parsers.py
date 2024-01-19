from django.test import TestCase
from datetime import datetime, timezone
from dateutil.parser import parse
from copy import deepcopy
import uuid
from hermes.management.commands.inject_message import BASE_LVC_COUNTERPART, BASE_GCN_CIRCULAR, BASE_LVK_MESSAGE, BASE_ICECUBE_CASCADE
from hermes.models import Message, NonLocalizedEvent, NonLocalizedEventSequence, Target
from hermes.parsers import GCNCircularParser, GCNNoticePlaintextParser, IGWNAlertParser, IcecubeNoticePlaintextParser


def get_lvk_notice_data(type, event_id, sequence_number=1, published=datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(), skymap_version=0):
    data = deepcopy(BASE_LVK_MESSAGE)
    base_type = type.split('_')[1]
    data['superevent_id'] = event_id
    data['alert_type'] = base_type
    data['time_created'] = published
    data['sequence_num'] = sequence_number
    data['event']['skymap_version'] = skymap_version
    data['event']['skymap_hash'] = uuid.uuid4().hex
    return data


def get_lvc_counterpart_text(type, event_id, target_ra=33.3, target_dec=22.2, source_sernum=1, author='N/A', published=datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()):
    return BASE_LVC_COUNTERPART.format(type=type, event_id=event_id, target_ra=target_ra, target_dec=target_dec, source_sernum=source_sernum, author=author, published=published)


def get_icecube_text(type, event_id, target_ra=44.4, target_dec=55.5, sequence_number=0, published=datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()):
    return BASE_ICECUBE_CASCADE.format(type=type, event_id=event_id, sequence_number=sequence_number, target_ra=target_ra, target_dec=target_dec, published=published)


def get_gcn_circular_header(event_id, author='N/A', published=datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()):
    header = deepcopy(BASE_GCN_CIRCULAR['header'])
    header['subject'] = header['subject'].format(event_id=event_id)
    header['from'] = header['from'].format(author=author)
    header['date'] = header['date'].format(published=published)
    return header


class TestLVCNoticeParser(TestCase):
    def setUp(self) -> None:
        super().setUp()
    
    def test_nonlocalizedevent_created(self):
        event_id = 'S112233'
        with self.assertRaises(NonLocalizedEvent.DoesNotExist):
            NonLocalizedEvent.objects.get(event_id=event_id)
        message, _ = Message.objects.get_or_create(
            topic='test_topic',
            data=get_lvk_notice_data(type='LVC_PRELIMINARY', event_id=event_id)
        )
        self.assertTrue(IGWNAlertParser().parse(message))
        event = NonLocalizedEvent.objects.get(event_id=event_id)
        self.assertEqual(event.event_id, event_id)

    def test_nonlocalizedevent_sequences_created(self):
        event_id = 'S112233'
        with self.assertRaises(NonLocalizedEvent.DoesNotExist):
            NonLocalizedEvent.objects.get(event_id=event_id)
        message, _ = Message.objects.get_or_create(
            topic='test_topic',
            data=get_lvk_notice_data(type='LVC_PRELIMINARY', event_id=event_id, sequence_number=1)
        )
        self.assertTrue(IGWNAlertParser().parse(message))
        same_data = get_lvk_notice_data(type='LVC_INITIAL', event_id=event_id, sequence_number=2, skymap_version=1)
        message, _ = Message.objects.get_or_create(
            topic='test_topic',
            data=same_data
        )
        self.assertTrue(IGWNAlertParser().parse(message))
        # Add a duplicate of one sequence_number to show it does not get added
        message, _ = Message.objects.get_or_create(
            topic='test_topic',
            data=same_data
        )
        self.assertTrue(IGWNAlertParser().parse(message))
        sequences = NonLocalizedEventSequence.objects.filter(event__event_id=event_id)
        self.assertEqual(sequences.count(), 2)
        self.assertEqual(sequences[0].sequence_number, 1)
        self.assertEqual(sequences[0].sequence_type, 'PRELIMINARY')
        self.assertEqual(sequences[1].sequence_number, 2)
        self.assertEqual(sequences[1].sequence_type, 'INITIAL')

    def test_fail_to_if_alert_missing_keywords(self):
        # Expected 'alert_type', 'superevent_id', 'time_created', and 'sequence_num' in data
        event_id = 'S123454'
        bad_data = get_lvk_notice_data(type='LVC_INITIAL', event_id=event_id, sequence_number=2, skymap_version=1)
        del bad_data['alert_type']
        message, _ = Message.objects.get_or_create(
            topic='test_topic',
            data=bad_data
        )
        self.assertFalse(IGWNAlertParser().parse(message))
        with self.assertRaises(NonLocalizedEvent.DoesNotExist):
            NonLocalizedEvent.objects.get(event_id=event_id)


class TestLVCCounterpartParser(TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.event_id = 'S123321'
        data = get_lvk_notice_data(type='LVC_INITIAL', event_id=self.event_id )
        self.message, _ = Message.objects.get_or_create(
            topic='test_topic',
            data=data
        )
        IGWNAlertParser().parse(self.message)
        self.message.refresh_from_db()
        self.event = NonLocalizedEvent.objects.get(event_id=self.event_id)

    def test_published_date_updated_with_obs_date(self):
        # This is pulled from the test counterpart text
        obs_date = datetime(2019, 4, 26, 20, 24, 8, tzinfo=timezone.utc)
        message, _ = Message.objects.get_or_create(
            topic='test_topic',
            message_text=get_lvc_counterpart_text(type='LVC_COUNTERPART', event_id=self.event_id)
        )
        # Initially, published is set to ingestion time until it is parsed from message_text
        self.assertGreater(message.published, obs_date)
        self.assertTrue(GCNNoticePlaintextParser().parse(message))
        message.refresh_from_db()
        # Now published time has been parsed from the message
        self.assertEqual(obs_date, message.published)

    def test_author_is_set(self):
        author = 'Test Author <test_author@mail.com>'
        message, _ = Message.objects.get_or_create(
            topic='test_topic',
            message_text=get_lvc_counterpart_text(type='LVC_COUNTERPART', event_id=self.event_id, author=author)
        )
        self.assertEqual(message.authors, "")
        self.assertTrue(GCNNoticePlaintextParser().parse(message))
        message.refresh_from_db()
        self.assertEqual(author, message.authors)

    def test_target_created_and_linked(self):
        target_ra = 52.3
        target_dec = 66.23
        source_sernum = 23
        target_name = f'{self.event_id}_X{source_sernum}'
        message, _ = Message.objects.get_or_create(
            topic='test_topic',
            message_text=get_lvc_counterpart_text(
                type='LVC_COUNTERPART', event_id=self.event_id, target_ra=target_ra, target_dec=target_dec, source_sernum=source_sernum
            )
        )
        self.assertTrue(GCNNoticePlaintextParser().parse(message))
        message.refresh_from_db()
        self.assertEqual(message.targets.count(), 1)
        target = message.targets.first()
        self.assertEqual(target.name, target_name)
        self.assertEqual(target.coordinate.x, target_ra)
        self.assertEqual(target.coordinate.y, target_dec)

    def test_two_targets_with_same_name_but_different_coord_linked(self):
        source_sernum = 23
        target_name = f'{self.event_id}_X{source_sernum}'
        target1_ra = 52.3
        target1_dec = 66.23
        message1, _ = Message.objects.get_or_create(
            topic='test_topic',
            message_text=get_lvc_counterpart_text(
                type='LVC_COUNTERPART', event_id=self.event_id, target_ra=target1_ra, target_dec=target1_dec, source_sernum=source_sernum
            )
        )
        self.assertTrue(GCNNoticePlaintextParser().parse(message1))
        target2_ra = 38.559
        target2_dec = 17.683
        message2, _ = Message.objects.get_or_create(
            topic='test_topic',
            message_text=get_lvc_counterpart_text(
                type='LVC_COUNTERPART', event_id=self.event_id, target_ra=target2_ra, target_dec=target2_dec, source_sernum=source_sernum
            )
        )
        self.assertTrue(GCNNoticePlaintextParser().parse(message2))
        message1.refresh_from_db()
        message2.refresh_from_db()
        targets = Target.objects.all()
        self.assertEqual(targets.count(), 2)
        self.assertEqual(targets[0].name, target_name)
        self.assertEqual(targets[1].name, target_name)
        self.assertEqual(targets[0].coordinate.x, target1_ra)
        self.assertEqual(targets[0].coordinate.y, target1_dec)
        self.assertEqual(targets[1].coordinate.x, target2_ra)
        self.assertEqual(targets[1].coordinate.y, target2_dec)

    def test_fail_to_parse_if_title_doesnt_contain_keywords(self):
        # Expected keywords are LVC, GCN, and NOTICE
        bad_message = 'TITLE:            BAD NOTICE\nTRIGGER_NUM:       S112233\nSEQUENCE_NUM:      1'
        message, _ = Message.objects.get_or_create(
            topic='test_topic',
            message_text=bad_message
        )
        self.assertFalse(GCNNoticePlaintextParser().parse(message))
        message.refresh_from_db()
        self.assertIsNone(message.data)
        self.assertEqual(message.title, '')


class TestIcecubeParser(TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.test_run_num = 138069

    def test_nonlocalizedevent_and_target_created(self):
        event_id = '11223344'
        full_event_id = f'{self.test_run_num}_{event_id}'
        target_ra = 44.44
        target_dec = 55.55
        with self.assertRaises(NonLocalizedEvent.DoesNotExist):
            NonLocalizedEvent.objects.get(event_id=full_event_id)
        message, _ = Message.objects.get_or_create(
            topic='test_topic',
            message_text=get_icecube_text(type='ICECUBE_CASCADE', event_id=event_id, target_ra=target_ra, target_dec=target_dec)
        )
        self.assertTrue(IcecubeNoticePlaintextParser().parse(message))
        event = NonLocalizedEvent.objects.get(event_id=full_event_id)
        self.assertEqual(event.event_id, full_event_id)

        expected_target_name = f"icecube_{full_event_id}_src"
        target = Target.objects.get(name=expected_target_name)
        self.assertEqual(event.event_id, full_event_id)
        self.assertEqual(target.coordinate.x, target_ra)
        self.assertEqual(target.coordinate.y, target_dec)

    def test_nonlocalizedevent_sequences_created(self):
        event_id = '11223344'
        full_event_id = f'{self.test_run_num}_{event_id}'
        with self.assertRaises(NonLocalizedEvent.DoesNotExist):
            NonLocalizedEvent.objects.get(event_id=full_event_id)
        message, _ = Message.objects.get_or_create(
            topic='test_topic',
            message_text=get_icecube_text(type='ICECUBE_CASCADE', event_id=event_id, sequence_number=0, target_ra=12.3, target_dec=23.4)
        )
        self.assertTrue(IcecubeNoticePlaintextParser().parse(message))
        message, _ = Message.objects.get_or_create(
            topic='test_topic',
            message_text=get_icecube_text(type='ICECUBE_CASCADE', event_id=event_id, sequence_number=1, target_ra=34.5, target_dec=45.6)
        )
        self.assertTrue(IcecubeNoticePlaintextParser().parse(message))

        sequences = NonLocalizedEventSequence.objects.filter(event__event_id=full_event_id)
        self.assertEqual(sequences.count(), 2)
        self.assertEqual(sequences[0].sequence_number, 0)
        self.assertEqual(sequences[0].sequence_type, 'INITIAL')
        self.assertEqual(sequences[1].sequence_number, 1)
        self.assertEqual(sequences[1].sequence_type, 'UPDATE')

    def test_gcn_url_is_added_on_ingestion(self):
        # Expected 'alert_type', 'superevent_id', 'time_created', and 'sequence_num' in data
        event_id = '11223344'
        full_event_id = f'{self.test_run_num}_{event_id}'
        with self.assertRaises(NonLocalizedEvent.DoesNotExist):
            NonLocalizedEvent.objects.get(event_id=full_event_id)
        message, _ = Message.objects.get_or_create(
            topic='test_topic',
            message_text=get_icecube_text(type='ICECUBE_CASCADE', event_id=event_id, sequence_number=0, target_ra=12.3, target_dec=23.4)
        )
        self.assertTrue(IcecubeNoticePlaintextParser().parse(message))
        expected_link = {
            'urls': {
                'gcn': f'https://gcn.gsfc.nasa.gov/notices_amon_icecube_cascade/{full_event_id}.amon'
            }
        }
        self.assertDictContainsSubset(expected_link, message.data)


class TestGCNCircularParser(TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.event_id = 'S123321'
        data = get_lvk_notice_data(type='LVC_INITIAL', event_id=self.event_id )
        self.message, _ = Message.objects.get_or_create(
            topic='test_topic',
            data=data
        )
        IGWNAlertParser().parse(self.message)
        self.message.refresh_from_db()
        self.event = NonLocalizedEvent.objects.get(event_id=self.event_id)

    def test_circular_message_add_gcn_link(self):
        author = 'Test Author <testauthor@mail.com>'
        published = datetime(2020, 1, 5, 12, 23, 44, tzinfo=timezone.utc)
        header = get_gcn_circular_header(self.event_id, author=author, published=published)
        message, _ = Message.objects.get_or_create(
                topic='Test Topic',
                authors=header['from'],
                published=parse(header['date']),
                title=header['subject'],
                message_text=BASE_GCN_CIRCULAR['body'],
                data=header
            )
        self.assertTrue(GCNCircularParser().parse(message))
        expected_link = {
            'urls': {
                'gcn_circular': f'https://gcn.nasa.gov/circulars/{header["number"]}'
            }
        }
        self.assertDictContainsSubset(expected_link, message.data)

    def test_circular_message_creates_nonlocalized_event_if_it_doesnt_exist(self):
        event_id = 'S654321'
        with self.assertRaises(NonLocalizedEvent.DoesNotExist):
            NonLocalizedEvent.objects.get(event_id=event_id)
        header = get_gcn_circular_header(event_id)
        message, _ = Message.objects.get_or_create(
                topic='Test Topic',
                authors=header['from'],
                published=parse(header['date']),
                title=header['subject'],
                message_text=BASE_GCN_CIRCULAR['body'],
                data=header
            )
        self.assertTrue(GCNCircularParser().parse(message))
        event = NonLocalizedEvent.objects.get(event_id=event_id)
        self.assertEqual(message.id, event.references.first().id)

    def test_circular_message_matches_two_nonlocalized_events(self):
        event_id2 = 'S654321'
        with self.assertRaises(NonLocalizedEvent.DoesNotExist):
            NonLocalizedEvent.objects.get(event_id=event_id2)
        header = get_gcn_circular_header(self.event_id)
        header['subject'] = f'This circular relates to events {self.event_id} and {event_id2}.'
        message, _ = Message.objects.get_or_create(
                topic='Test Topic',
                authors=header['from'],
                published=parse(header['date']),
                title=header['subject'],
                message_text=BASE_GCN_CIRCULAR['body'],
                data=header
            )
        self.assertTrue(GCNCircularParser().parse(message))
        event2 = NonLocalizedEvent.objects.get(event_id=event_id2)
        self.assertEqual(message.id, self.event.references.first().id)
        self.assertEqual(message.id, event2.references.first().id)

    def test_circular_message_doesnt_parse_with_bad_title(self):
        header = get_gcn_circular_header(self.event_id)
        header['title'] = 'Bad Title'
        message, _ = Message.objects.get_or_create(
                topic='Test Topic',
                authors=header['from'],
                published=parse(header['date']),
                title=header['subject'],
                message_text=BASE_GCN_CIRCULAR['body'],
                data=header
            )
        self.assertFalse(GCNCircularParser().parse(message))
        self.assertEqual(self.event.references.count(), 0)
