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


def get_lvc_counterpart_text(event_id, target_ra=33.3, target_dec=22.2, source_sernum=1):
    data = deepcopy(BASE_LVC_COUNTERPART)
    data['event_trig_num'] = event_id
    data['source_sernum'] = source_sernum
    data['cntrpart_ra'] = f"{target_ra}d,"
    data['cntrpart_dec'] = f"{target_dec}d,"
    return data


def get_icecube_text(type, event_id, target_ra=44.4, target_dec=55.5, sequence_number=0, revision=0):
    data = deepcopy(BASE_ICECUBE_CASCADE)
    data['event_num'] = event_id
    data['run_num'] = sequence_number
    data['revision'] = f"{revision}"
    data['src_ra'] = f"{target_ra}d,"
    data['src_dec'] = f"{target_dec}d,"
    data['notice_type'] = type
    return data


def get_gcn_circular_header(event_id, author='N/A', published=datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()):
    data = deepcopy(BASE_GCN_CIRCULAR)
    data['subject'] = data['subject'].format(event_id=event_id)
    data['eventId'] = event_id
    data['submitter'] = data['submitter'].format(author=author)
    data['createdOn'] = data['createdOn'].format(published=published)
    return data


class TestLVCNoticeParser(TestCase):
    def setUp(self) -> None:
        super().setUp()
    
    def test_nonlocalizedevent_created(self):
        event_id = 'S112233'
        with self.assertRaises(NonLocalizedEvent.DoesNotExist):
            NonLocalizedEvent.objects.get(event_id=event_id)
        message = Message.objects.create()
        data = get_lvk_notice_data(type='LVC_PRELIMINARY', event_id=event_id)
        self.assertTrue(IGWNAlertParser().parse(message, data))
        event = NonLocalizedEvent.objects.get(event_id=event_id)
        self.assertEqual(event.event_id, event_id)

    def test_nonlocalizedevent_sequences_created(self):
        event_id = 'S112233'
        with self.assertRaises(NonLocalizedEvent.DoesNotExist):
            NonLocalizedEvent.objects.get(event_id=event_id)
        message = Message.objects.create()
        data = get_lvk_notice_data(type='LVC_PRELIMINARY', event_id=event_id, sequence_number=1)
        self.assertTrue(IGWNAlertParser().parse(message, data))
        same_data = get_lvk_notice_data(type='LVC_INITIAL', event_id=event_id, sequence_number=2, skymap_version=1)
        message = Message.objects.create()
        self.assertTrue(IGWNAlertParser().parse(message, same_data))
        # Add a duplicate of one sequence_number to show it does not get added
        message = Message.objects.create()
        self.assertTrue(IGWNAlertParser().parse(message, same_data))
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
        message = Message.objects.create()
        self.assertFalse(IGWNAlertParser().parse(message, bad_data))
        with self.assertRaises(NonLocalizedEvent.DoesNotExist):
            NonLocalizedEvent.objects.get(event_id=event_id)


class TestLVCCounterpartParser(TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.event_id = 'S123321'
        data = get_lvk_notice_data(type='LVC_INITIAL', event_id=self.event_id )
        self.message = Message.objects.create()
        IGWNAlertParser().parse(self.message, data)
        self.message.refresh_from_db()
        self.event = NonLocalizedEvent.objects.get(event_id=self.event_id)

    def test_target_created_and_linked(self):
        target_ra = 52.3
        target_dec = 66.23
        source_sernum = 23
        target_name = f'{self.event_id}_X{source_sernum}'
        message = Message.objects.create()
        data = get_lvc_counterpart_text(event_id=self.event_id, target_ra=target_ra, target_dec=target_dec, source_sernum=source_sernum)
        self.assertTrue(GCNNoticePlaintextParser().parse(message, data))
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
        message1 = Message.objects.create()
        data = get_lvc_counterpart_text(event_id=self.event_id, target_ra=target1_ra, target_dec=target1_dec, source_sernum=source_sernum)
        self.assertTrue(GCNNoticePlaintextParser().parse(message1, data))
        target2_ra = 38.559
        target2_dec = 17.683
        message2 = Message.objects.create()
        data=get_lvc_counterpart_text(event_id=self.event_id, target_ra=target2_ra, target_dec=target2_dec, source_sernum=source_sernum)
        self.assertTrue(GCNNoticePlaintextParser().parse(message2, data))
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
        bad_data = {
            'title': 'BAD NOTICE',
            'trigger_num': 'S112233',
            'sequence_num': '1'
        }
        message = Message.objects.create()
        self.assertFalse(GCNNoticePlaintextParser().parse(message, bad_data))
        message.refresh_from_db()
        self.assertEqual(Target.objects.count(), 0)


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
        message = Message.objects.create()
        data = get_icecube_text(type='ICECUBE_CASCADE', event_id=event_id, sequence_number=self.test_run_num, target_ra=target_ra, target_dec=target_dec)
        self.assertTrue(IcecubeNoticePlaintextParser().parse(message, data))
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
        message = Message.objects.create()
        data = get_icecube_text(type='ICECUBE_CASCADE', event_id=event_id, sequence_number=self.test_run_num, target_ra=12.3, target_dec=23.4)
        self.assertTrue(IcecubeNoticePlaintextParser().parse(message, data))
        message = Message.objects.create()
        data = get_icecube_text(type='ICECUBE_CASCADE', event_id=event_id, sequence_number=self.test_run_num, target_ra=34.5, target_dec=45.6, revision=1)
        self.assertTrue(IcecubeNoticePlaintextParser().parse(message, data))

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
        message = Message.objects.create()
        data = get_icecube_text(type='ICECUBE_CASCADE', event_id=event_id, sequence_number=self.test_run_num, target_ra=12.3, target_dec=23.4)
        self.assertTrue(IcecubeNoticePlaintextParser().parse(message, data))
        nles = NonLocalizedEventSequence.objects.first()
        expected_link = {
            'urls': {
                'gcn': f'https://gcn.gsfc.nasa.gov/notices_amon_icecube_cascade/{full_event_id}.amon'
            }
        }
        self.assertDictContainsSubset(expected_link, nles.data)


class TestGCNCircularParser(TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.event_id = 'S123321'
        data = get_lvk_notice_data(type='LVC_INITIAL', event_id=self.event_id )
        self.message = Message.objects.create()
        IGWNAlertParser().parse(self.message, data)
        self.message.refresh_from_db()
        self.event = NonLocalizedEvent.objects.get(event_id=self.event_id)

    def test_circular_message_creates_nonlocalized_event_if_it_doesnt_exist(self):
        event_id = 'S654321'
        with self.assertRaises(NonLocalizedEvent.DoesNotExist):
            NonLocalizedEvent.objects.get(event_id=event_id)
        data = get_gcn_circular_header(event_id)
        message = Message.objects.create()
        self.assertTrue(GCNCircularParser().parse(message, data))
        event = NonLocalizedEvent.objects.get(event_id=event_id)
        self.assertEqual(message.id, event.references.first().id)

    def test_circular_message_doesnt_parse_with_no_id(self):
        data = get_gcn_circular_header(self.event_id)
        del data['circularId']
        message = Message.objects.create()
        self.assertFalse(GCNCircularParser().parse(message, data))
        self.assertEqual(self.event.references.count(), 0)
