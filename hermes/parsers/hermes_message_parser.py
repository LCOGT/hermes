from django.contrib.gis.geos import Point

from hermes.models import NonLocalizedEvent, Target
from hermes.parsers.base_parser import BaseParser
import logging

logger = logging.getLogger(__name__)


class HermesMessageParser(BaseParser):
    """ Hermes messages come in in the correct format already, so this parser is just
        to link a NonLocalizedEvent if `event_id` is present in the data, and to link any targets
        by target_name, ra, dec combos at any level in the data structure. 
    """

    def __repr__(self):
        return 'Hermes Message Parser v1'

    def parse_message(self, message):
        ''' Hermes messages automatically come with json data, so we just need to do linking on them
        '''
        message.message_parser = repr(self)
        message.save()
        self.link_message(message)
        return True

    def find_and_link_targets(self, structure, message):
        if isinstance(structure, dict):
            if 'target_name' in structure and 'ra' in structure and 'dec' in structure:
                    target, _ = Target.objects.get_or_create(name=structure['target_name'], coordinates=Point(float(structure['ra']), float(structure['dec']), srid=4035))
                    if not target.messages.contains(message):
                        target.messages.add(message)
                        target.save()
            else:
                for value in structure.values():
                    if isinstance(value, (list, dict)):
                        self.find_and_link_targets(value, message)
        elif isinstance(structure, list):
            for value in structure:
                if isinstance(value, (list, dict)):
                    self.find_and_link_targets(value, message)


    def link_message(self, message):
        ''' Attempt to link or create extra models to relate targets or nonlocalized events to this message
        '''
        data = message.data
        if data:
            return
        if 'event_id' in data:
            nonlocalizedevent, _ = NonLocalizedEvent.objects.get_or_create(event_id=data['event_id'])
            if not nonlocalizedevent.references.contains(message):
                nonlocalizedevent.references.add(message)
                nonlocalizedevent.save()
        self.find_and_link_targets(data, message)

    def parse(self, message):
        try:
            return self.parse_message(message)
        except Exception as e:
            logger.warn(f'Unable to parse Message {message.id} with parser {self}: {e}')
            return False
