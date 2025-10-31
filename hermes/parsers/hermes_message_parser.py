from django.contrib.gis.geos import Point

from hermes.models import NonLocalizedEvent, Target
from hermes.parsers.base_parser import BaseParser
import logging

logger = logging.getLogger(__name__)


class HermesMessageParser(BaseParser):
    """ Hermes messages come in in the correct format already, so this parser is just
        to link a NonLocalizedEvent if `event_id` is present in the data, and to link any targets
        by target_name, ra, dec combos in the `targets` section.
    """

    def __repr__(self):
        return 'Hermes Message Parser v2'

    def parse_message(self, message, data):
        ''' Hermes messages automatically come with json data, so we just need to do linking on them
        '''
        self.link_message(message, data.get('data', {}))
        return True

    def link_targets(self, message, data):
        for target_details in data.get('targets', []):
            if target_details.get('ra') and target_details.get('dec'):
                target, _ = Target.objects.get_or_create(
                    name=target_details['name'],
                    coordinate=Point(float(target_details['ra']), float(target_details['dec']), srid=4035)
                )
                if not target.messages.contains(message):
                    target.messages.add(message)
                    target.save()

    def link_message(self, message, data):
        ''' Attempt to link or create extra models to relate targets or nonlocalized events to this message
        '''
        if 'event_id' in data:
            nonlocalizedevent, _ = NonLocalizedEvent.objects.get_or_create(event_id=data['event_id'])
            if not nonlocalizedevent.references.contains(message):
                nonlocalizedevent.references.add(message)
                nonlocalizedevent.save()
        self.link_targets(message, data)

    def parse(self, message, data):
        try:
            return self.parse_message(message, data)
        except Exception as e:
            logger.warn(f'Unable to parse Message {message.id} with parser {self}: {e}')
            return False
