import logging
import uuid

from hermes.models import NonLocalizedEvent, NonLocalizedEventSequence
from hermes.parsers.base_parser import BaseParser


logger = logging.getLogger(__name__)


class IGWNAlertParser(BaseParser):
    """
    Sample IGWN Alert Avro Schema:
    {
        'alert_type': 'PRELIMINARY',
        'event': {'central_frequency': None,
                'classification': {'BBH': 0.03,
                                    'BNS': 0.95,
                                    'NSBH': 0.01,
                                    'Terrestrial': 0.01},
                'duration': None,
                'far': 9.11069936486e-14,
                'group': 'CBC',
                'instruments': ['H1', 'L1', 'V1'],
                'pipeline': 'gstlal',
                'properties': {'HasMassGap': 0.01,
                                'HasNS': 0.95,
                                'HasRemnant': 0.91},
                'search': 'MDC',
                'significant': True,
                'time': '2018-11-01T22:22:46.654Z'},
        'external_coinc': None,
        'superevent_id': 'MS181101ab',
        'time_created': '2018-11-01T22:34:49Z',
        'urls': {'gracedb': 'https://gracedb.ligo.org/superevents/MS181101ab/view/'}
    }
    In ingesting these alerts, we add in some other critical info for their efficient storage / linking
    {
        'sequence_number': 1,
        'event': {
            'skymap_version': 1,
            'skymap_hash': 'bbc9a5ac5f13f921b8f4bd66aac444cd'
        },
        'external_coinc': {
            'combined_skymap_version': 0,
            'combined_skymap_hash': 'bbc9a5ac5f13f921b8f4bd66aac444cd'
        },
        urls: {
            'skymap': 'https://gracedb.ligo.org/api/superevents/MS181101ab/files/bayestar.multiorder.fits,1',
            'combined_skymap': 'https://gracedb.ligo.org/api/superevents/MS181101ab/files/combined-ext.multiorder.fits,0'
        }
    }
    """
    REQUIRED_KEYS = ['alert_type', 'time_created', 'superevent_id', 'sequence_num']

    def __repr__(self):
        return 'IGWN Alert Avro Parser v1'

    def parse_message(self, message, data):
        # Avro formatted data will likely be placed in the data field, not message_text
        if all([key in data for key in self.REQUIRED_KEYS]):
            self.link_message(message, data)
            return True
        return False

    def link_message(self, message, data):
        ''' Attempt to link or create extra models to relate targets or nonlocalized events to this message
        '''
        nonlocalizedevent, _ = NonLocalizedEvent.objects.get_or_create(event_id = data['superevent_id'])
        notice_type = self.convert_notice_type(data.get('alert_type', ''))
        NonLocalizedEventSequence.objects.get_or_create(
            message=message, event=nonlocalizedevent, sequence_number=data['sequence_num'], sequence_type=notice_type,
            data=data,
        )

    def parse(self, message, data):
        return self.parse_message(message, data)
