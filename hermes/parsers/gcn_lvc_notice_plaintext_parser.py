import logging
from datetime import timezone

from dateutil.parser import parse

from hermes.models import NonLocalizedEvent, NonLocalizedEventSequence
from hermes.parsers.base_parser import BaseParser


logger = logging.getLogger(__name__)


class GCNLVCNoticeParser(BaseParser):
    """
    Sample GCN/LVC Notice:

    TITLE:            GCN/LVC NOTICE
    NOTICE_DATE:      Mon 16 Mar 20 22:01:09 UT
    NOTICE_TYPE:      LVC Preliminary
    TRIGGER_NUM:      S200316bj
    TRIGGER_DATE:     18924 TJD;    76 DOY;   2020/03/16 (yyyy/mm/dd)
    TRIGGER_TIME:     79076.157221 SOD {21:57:56.157221} UT
    SEQUENCE_NUM:     1
    GROUP_TYPE:       1 = CBC
    SEARCH_TYPE:      1 = AllSky
    PIPELINE_TYPE:    4 = gstlal
    FAR:              7.099e-11 [Hz]  (one per 163037.0 days)  (one per 446.68 years)
    PROB_NS:          0.00 [range is 0.0-1.0]
    PROB_REMNANT:     0.00 [range is 0.0-1.0]
    PROB_BNS:         0.00 [range is 0.0-1.0]
    PROB_NSBH:        0.00 [range is 0.0-1.0]
    PROB_BBH:         0.00 [range is 0.0-1.0]
    PROB_MassGap:     0.99 [range is 0.0-1.0]
    PROB_TERRES:      0.00 [range is 0.0-1.0]
    TRIGGER_ID:       0x10
    MISC:             0x1898807
    SKYMAP_FITS_URL:  https://gracedb.ligo.org/api/superevents/S200316bj/files/bayestar.fits.gz,0
    EVENTPAGE_URL:    https://gracedb.ligo.org/superevents/S200316bj/view/
    COMMENTS:         LVC Preliminary Trigger Alert.
    COMMENTS:         This event is an OpenAlert.
    COMMENTS:         LIGO-Hanford Observatory contributed to this candidate event.
    COMMENTS:         LIGO-Livingston Observatory contributed to this candidate event.
    COMMENTS:         VIRGO Observatory contributed to this candidate event.
    """

    def __repr__(self):
        return 'GCN/LVC Notice Parser v1'
    
    def add_extra_fields(self, parsed_fields):
        ''' Add and modify some of the parsed fields
            Changes skymap fits url to be the multiorder version if it is not
            Also reads from that file and adds the area_50 and area_90 header values to the dict
        '''
        if 'skymap_fits_url' in parsed_fields:
            parsed_fields['skymap_fits_url'] = self.get_moc_url_from_skymap_fits_url(parsed_fields['skymap_fits_url'])
            area_50, area_90 = self.get_confidence_regions(parsed_fields.get('skymap_fits_url', ''))
            parsed_fields['area_50'] = area_50 if area_50 else ''
            parsed_fields['area_90'] = area_90 if area_90 else ''
        return parsed_fields

    def parse_message(self, message):
        raw_message = message.message_text
        parsed_fields = {}
        try:
            for line in raw_message.splitlines():
                entry = line.split(':', maxsplit=1)
                if len(entry) > 1:
                    if entry[0].strip() == 'COMMENTS' and 'comments' in parsed_fields:
                        parsed_fields['comments'] += entry[1].lstrip()
                    else:
                        parsed_fields[entry[0].strip().lower()] = entry[1].strip()
        except Exception as e:
            logger.warn(f'parse_message failed for lvc notice Message {message.id}: {e}')
        
        if parsed_fields and all(x.lower() in parsed_fields['title'].lower() for x in ['GCN', 'LVC', 'NOTICE']):
            parsed_fields = self.add_extra_fields(parsed_fields)
            message.data = parsed_fields
            if 'notice_date' in parsed_fields:
                message.published = parse(parsed_fields['notice_date'], tzinfos={'UT': timezone.utc})
            message.message_parser = repr(self)
            message.title = parsed_fields['title']
            message.save()
            self.link_message(message)
            return True
        return False

    def link_message(self, message):
        ''' Attempt to link or create extra models to relate targets or nonlocalized events to this message
        '''
        if not message.data:
            return
        if 'trigger_num' in message.data:
            nonlocalizedevent, _ = NonLocalizedEvent.objects.get_or_create(event_id = message.data['trigger_num'])
            if 'sequence_num' in message.data:
                notice_type = self.convert_notice_type(message.data.get('notice_type', ''))
                NonLocalizedEventSequence.objects.get_or_create(
                    event=nonlocalizedevent, sequence_number=message.data['sequence_num'], sequence_type=notice_type,
                    defaults={
                        'message': message
                    }
                )

    def parse(self, message):
        try:
            return self.parse_message(message)
        except Exception as e:
            logger.warn(f'Unable to parse Message {message.id} with parser {self}: {e}')
            return False
