from dateutil.parser import parse
from datetime import datetime, timezone
import logging
import re

from django.contrib.gis.geos import Point

from hermes.models import NonLocalizedEvent, NonLocalizedEventSequence, Target
from hermes.parsers.base_parser import BaseParser


logger = logging.getLogger(__name__)


class GCNLVCCounterpartNoticeParser(BaseParser):
    """
    Sample GCN/LVC Counterpart Notice:

    TITLE:            GCN/LVC COUNTERPART NOTICE
    NOTICE_DATE:      Fri 26 Apr 19 23:13:39 UT
    NOTICE_TYPE:      Other
    CNTRPART_RA:      299.8851d {+19h 59m 32.4s} (J2000),
                      300.0523d {+20h 00m 12.5s} (current),
                      299.4524d {+19h 57m 48.5s} (1950)
    CNTRPART_DEC:     +40.7310d {+40d 43' 51.6"} (J2000),
                      +40.7847d {+40d 47' 04.9"} (current),
                      +40.5932d {+40d 35' 35.4"} (1950)
    CNTRPART_ERROR:   7.6 [arcsec, radius]
    EVENT_TRIG_NUM:   S190426
    EVENT_DATE:       18599 TJD;   116 DOY;   2019/04/26 (yy/mm/dd)
    EVENT_TIME:       55315.00 SOD {15:21:55.00} UT
    OBS_DATE:         18599 TJD;   116 DOY;   19/04/26
    OBS_TIME:         73448.0 SOD {20:24:08.00} UT
    OBS_DUR:          72.7 [sec]
    INTENSITY:        1.00e-11 +/- 2.00e-12 [erg/cm2/sec]
    ENERGY:           0.3-10 [keV]
    TELESCOPE:        Swift-XRT
    SOURSE_SERNUM:    2
    RANK:             2
    WARN_FLAG:        0
    SUBMITTER:        Phil_Evans
    SUN_POSTN:         34.11d {+02h 16m 26s}  +13.66d {+13d 39' 45"}
    SUN_DIST:          84.13 [deg]   Sun_angle= 6.3 [hr] (West of Sun)
    MOON_POSTN:       309.58d {+20h 38m 19s}  -19.92d {-19d 55' 00"}
    MOON_DIST:         61.34 [deg]
    MOON_ILLUM:       50 [%]
    GAL_COORDS:        76.19,  5.74 [deg] galactic lon,lat of the counterpart
    ECL_COORDS:       317.73, 59.32 [deg] ecliptic lon,lat of the counterpart
    COMMENTS:         LVC Counterpart.
    COMMENTS:         This matches a catalogued X-ray source: 1RXH J195932.6+404351
    COMMENTS:         This source has been given a rank of 2
    COMMENTS:         Ranks indicate how likely the object is to be
    COMMENTS:         the GW counterpart. Ranks go from 1-4 with
    COMMENTS:         1 being the most likely and 4 the least.
    COMMENTS:         See http://www.swift.ac.uk/ranks.php for details.
    COMMENTS:         MAY match a known transient, will be checked manually.
    """

    def __repr__(self):
        return 'GCN/LVC Counterpart Notice Parser v1'

    def parse_target_name(self, parsed_fields):
        """
        Sources are of the format S123456_X1, that is, event trigger number + '_X' + source serial number
        """
        try:
            event_trigger_number = parsed_fields['event_trig_num']
            source_sernum = parsed_fields['sourse_sernum']
            return f'{event_trigger_number}_X{source_sernum}'
        except Exception as e:
            logger.warn(f'Unable to parse target name for lvc counterpart: {e}')
        return ''

    def parse_coordinates(self, parsed_fields):
        try:
            raw_ra = parsed_fields['cntrpart_ra'].split(',')[0]
            raw_dec = parsed_fields['cntrpart_dec'].split(',')[0]
            right_ascension = raw_ra.split('d', 1)[0]
            declination = raw_dec.split('d', 1)[0]
            return right_ascension, declination
        except Exception as e:
            logger.warn(f'Unable to parse coordinates for lvc counterpart: {e}')
        return None, None

    def parse_message(self, message):
        raw_message = message.message_text
        parsed_fields = {}

        try:
            last_entry = ''
            for line in raw_message.strip().splitlines():  # Remove leading/trailing newlines
                entry = line.split(':', maxsplit=1)
                if len(entry) > 1:
                    if entry[0].strip() == 'COMMENTS' and 'comments' in parsed_fields:
                        parsed_fields['comments'] += entry[1].lstrip()
                    else:
                        parsed_fields[entry[0].lower()] = entry[1].strip()
                else:
                    # RA is parsed first, so append to RA if dec hasn't been parsed
                    if last_entry == 'cntrpart_ra':
                        self.alert.parsed_message['cntrpart_ra'] += ' ' + entry[0].strip()
                    elif last_entry == 'cntrpart_dec':
                        self.alert.parsed_message['cntrpart_dec'] += ' ' + entry[0].strip()
                last_entry = entry[0]
        except Exception as e:
            logger.warn(f'parse_message failed for lvc counterpart Message {message.id}: {e}')
        
        if parsed_fields and all(x.lower() in parsed_fields.get('title', '').lower() for x in ['GCN', 'LVC', 'COUNTERPART', 'NOTICE']):
            message.data = parsed_fields
            message_date = self.parse_obs_timestamp(parsed_fields)
            if message_date:
                message.published = message_date
            message.message_parser = repr(self)
            message.save()
            self.link_message(message)
            return True
        return False

    def link_message(self, message):
        ''' Attempt to link or create extra models to relate targets or nonlocalized events to this message
        '''
        if not message.data:
            return
        if 'event_trig_num' in message.data:
            nonlocalizedevent, _ = NonLocalizedEvent.objects.get_or_create(event_id = message.data['event_trig_num'])
            if not nonlocalizedevent.references.contains(message):
                nonlocalizedevent.references.add(message)
                nonlocalizedevent.save()
            # Now parse the target as well
            right_ascension, declination = self.parse_coordinates(message.data)
            if right_ascension and declination:
                target_name = self.parse_target_name(message.data)
                if target_name:
                    target, _ = Target.objects.get_or_create(name=target_name, coordinate=Point(float(right_ascension), float(declination), srid=4035))
                    if not target.messages.contains(message):
                        target.messages.add(message)
                        target.save()


    def parse_obs_timestamp(self, parsed_fields):
        try:
            raw_datestamp = parsed_fields['obs_date']
            raw_timestamp = parsed_fields['obs_time']
            datestamp = re.search(r'\d{2}\/\d{2}\/\d{2}', raw_datestamp)
            parsed_datestamp = parse(datestamp.group(0), yearfirst=True)
            timestamp = re.search(r'\d{2}:\d{2}:\d{2}\.\d{2}', raw_timestamp)
            parsed_timestamp = parse(timestamp.group(0))
            combined_datetime = datetime.combine(parsed_datestamp, parsed_timestamp.time(), tzinfo=timezone.utc)
            return combined_datetime
        except Exception:
            return None

    def parse(self, message):
        try:
            return self.parse_message(message)
        except Exception as e:
            logger.warn(f'Unable to parse Message {message.id} with parser {self}: {e}')
            return False
