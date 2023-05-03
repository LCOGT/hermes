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

    def parse_message(self, message):
        # Avro formatted data will likely be placed in the data field, not message_text
        alert = message.data
        if all([key in alert for key in self.REQUIRED_KEYS]):
            message.message_parser = repr(self)
            message.save()
            self.link_message(message)
            return True
        return False

    def link_message(self, message):
        ''' Attempt to link or create extra models to relate targets or nonlocalized events to this message
        '''
        nonlocalizedevent, _ = NonLocalizedEvent.objects.get_or_create(event_id = message.data['superevent_id'])
        notice_type = self.convert_notice_type(message.data.get('alert_type', ''))
        skymap_hash = None
        skymap_version = None
        if message.data.get('event', {}) and 'skymap_hash' in message.data.get('event', {}):
            skymap_hash = uuid.UUID(message.data['event']['skymap_hash'])
            skymap_version = message.data.get('event', {}).get('skymap_version', None)
        combined_skymap_hash = None
        combined_skymap_version = None
        if message.data.get('external_coinc', {}) and 'combined_skymap_hash' in message.data.get('external_coinc', {}):
            combined_skymap_hash = uuid.UUID(message.data['external_coinc']['combined_skymap_hash'])
            combined_skymap_version = message.data.get('external_coinc', {}).get('combined_skymap_version', None)
        NonLocalizedEventSequence.objects.get_or_create(
            message=message, event=nonlocalizedevent, sequence_number=message.data['sequence_num'], sequence_type=notice_type,
            skymap_version=skymap_version, skymap_hash=skymap_hash,
            combined_skymap_version=combined_skymap_version, combined_skymap_hash=combined_skymap_hash
        )

    def parse(self, message):
        return self.parse_message(message)
        # try:
        #     return self.parse_message(message)
        # except Exception as e:
        #     logger.warn(f'Unable to parse Message {message.id} with parser {self}: {e}')
        #     return False
