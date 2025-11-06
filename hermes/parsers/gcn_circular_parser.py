import logging
import re

from dateutil.parser import parse, parserinfo

from hermes.models import NonLocalizedEvent
from hermes.parsers.base_parser import BaseParser


logger = logging.getLogger(__name__)


class GCNCircularParser(BaseParser):
    """
    Sample ``gcn-circular`` alert:

    {
        "subject": "LIGO/Virgo/KAGRA S240830gn: Identification of a GW compact binary merger candidate",
        "eventId": "LIGO/Virgo/KAGRA S240830gn",
        "submittedHow": "web",
        "createdOn": 1725054211876,
        "circularId": 37354,
        "submitter": "Person at Institution <email@domain>",
        "format": "text/plain",
        "body": "\nThe LIGO Scientific Collaboration, the Virgo Collaboration, and the KAGRA Collaboration report:...\n"
    }
    """

    def __repr__(self):
        return 'GCN Circular Parser v2'

    def link_message(self, message, data):
        superevent_regex = re.compile(r'S\d{6}[a-z]*')  # matches S######??, where ?? is any number of lowercase alphas
        if 'eventId' in data:
            matches = superevent_regex.findall(data['eventId'])
            for match in matches:
                nonlocalizedevent, _ = NonLocalizedEvent.objects.get_or_create(event_id=match)
                if not nonlocalizedevent.references.contains(message):
                    nonlocalizedevent.references.add(message)
                    nonlocalizedevent.save()

    def parse_message(self, message, data):
        ''' extra_data contains the header information for gcn circular messages
        '''
        if 'circularId' in data:
            self.link_message(message, data)
            return True
        return False

    def parse(self, message, data):
        try:
            return self.parse_message(message, data)
        except Exception as e:
            logger.warn(f'Unable to parse Message {message.id} with parser {self}: {e}')
            return False
