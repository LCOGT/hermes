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

    def parse_message(self, message):
        ''' Hermes messages automatically come with json data, so we just need to do linking on them
        '''
        message.message_parser = repr(self)
        message.save()
        self.link_message(message)
        return True

    def link_targets(self, data, message):
        for target_details in data.get('targets', []):
            if target_details.get('ra') and target_details.get('dec'):
                target, _ = Target.objects.get_or_create(
                    name=target_details['name'],
                    coordinate=Point(float(target_details['ra']), float(target_details['dec']), srid=4035)
                )
                if not target.messages.contains(message):
                    target.messages.add(message)
                    target.save()

    def link_message(self, message):
        ''' Attempt to link or create extra models to relate targets or nonlocalized events to this message
        '''
        data = message.data
        if not data:
            return
        if 'event_id' in data:
            nonlocalizedevent, _ = NonLocalizedEvent.objects.get_or_create(event_id=data['event_id'])
            if not nonlocalizedevent.references.contains(message):
                nonlocalizedevent.references.add(message)
                nonlocalizedevent.save()
        self.link_targets(data, message)

    def parse(self, message):
        try:
            return self.parse_message(message)
        except Exception as e:
            logger.warn(f'Unable to parse Message {message.id} with parser {self}: {e}')
            return False
