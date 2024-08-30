from dateutil.parser import parse
from datetime import datetime, timezone
import logging
import re

from django.contrib.gis.geos import Point

from hermes.models import NonLocalizedEvent, Target
from hermes.parsers.base_parser import BaseParser


logger = logging.getLogger(__name__)


class GCNNoticePlaintextParser(BaseParser):
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
    SOURCE_SERNUM:    2
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
        return 'GCN Notice Plaintext Parser v1'

    def parse_target(self, parsed_fields, event_id):
        """ Attempt to parse out a target name, ra, and dec from this alert.
            This currently only support LVC_COUNTERPART messages, but should be
            updated for GRB_COUNTERPARTS once we start ingesting GRB events.
        """
        target_name = ''
        ra = dec = None
        if 'source_sernum' in parsed_fields:
            target_name = f'{event_id}_X{parsed_fields["source_sernum"]}'
        if target_name:
            try:
                raw_ra = parsed_fields['cntrpart_ra'].split(',')[0]
                raw_dec = parsed_fields['cntrpart_dec'].split(',')[0]
                ra = raw_ra.split('d', 1)[0]
                dec = raw_dec.split('d', 1)[0]
            except Exception as e:
                logger.warn(f'Unable to parse coordinates for lvc counterpart gcn notice: {e}')
        return target_name, ra, dec

    def parse_message(self, message):
        parsed_fields = {}
        if not message.data:
            try:
                last_entry = ''
                for line in message.message_text.strip().splitlines():  # Remove leading/trailing newlines
                    entry = line.split(':', maxsplit=1)
                    if len(entry) > 1:
                        key = entry[0].strip().lower()
                        if key == last_entry and last_entry in parsed_fields:
                            # For multi-line values repeating the key, append the values here with a newline
                            parsed_fields[last_entry] += f'\n{entry[1].lstrip()}'
                        else:
                            parsed_fields[key] = entry[1].strip()
                        last_entry = key
                    else:
                        # Append multi-line values here to the previous key if a new key isn't present
                        if last_entry:
                            parsed_fields[last_entry] += ' ' + entry[0].strip()
            except Exception as e:
                logger.warn(f'parse_message failed for GCN Notice Message {message.id}: {e}')
        else:
            logger.warn("GCN Notice already has data dictionary so just use that")
            parsed_fields = message.data

        if parsed_fields and all(x.lower() in parsed_fields.get('title', '').lower() for x in ['GCN', 'NOTICE']):
            urls = self.generate_urls(parsed_fields)
            if urls and 'urls' not in parsed_fields:
                parsed_fields['urls'] = urls
            message.data = parsed_fields
            if 'title' in parsed_fields:
                message.title = parsed_fields['title']
            message_date = self.parse_published(parsed_fields)
            if message_date:
                message.published = message_date.replace(tzinfo=timezone.utc)
            submitter = self.parse_submitter(parsed_fields)
            if submitter:
                message.submitter = submitter
            authors = self.parse_authors(parsed_fields)
            if (not message.authors) and authors:
                message.authors = authors
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
        event_id = ''
        if 'event_trig_num' in message.data:
            event_id = message.data['event_trig_num']
        # TODO: enable this once GRB events are being injested to support GRB_COUNTERPARTS
        # elif 'trigger_num' in message.data:
        #     event_id = message.data['trigger_num']
        if event_id:
            nonlocalizedevent, _ = NonLocalizedEvent.objects.get_or_create(event_id = event_id)
            if not nonlocalizedevent.references.contains(message):
                nonlocalizedevent.references.add(message)
                nonlocalizedevent.save()
        # Now parse the target as well
        target_name, ra, dec = self.parse_target(message.data, event_id)
        if target_name and ra and dec:
            target, _ = Target.objects.get_or_create(name=target_name, coordinate=Point(float(ra), float(dec), srid=4035))
            if not target.messages.contains(message):
                target.messages.add(message)
                target.save()

    def parse_published(self, parsed_fields):
        try:
            if 'obs_date' in parsed_fields and 'obs_time' in parsed_fields:
                raw_datestamp = parsed_fields['obs_date']
                raw_timestamp = parsed_fields['obs_time']
                datestamp = re.search(r'\d{2}\/\d{2}\/\d{2}', raw_datestamp)
                parsed_datestamp = parse(datestamp.group(0), yearfirst=True)
                timestamp = re.search(r'\d{2}:\d{2}:\d{2}\.\d{2}', raw_timestamp)
                parsed_timestamp = parse(timestamp.group(0))
                combined_datetime = datetime.combine(parsed_datestamp, parsed_timestamp.time(), tzinfo=timezone.utc)
                return combined_datetime
            elif 'notice_date' in parsed_fields:
                # Fall back on notice_date
                return parse(parsed_fields['notice_date'], ignoretz=True)
        except Exception:
            pass
        return None

    def parse_submitter(self, parsed_fields):
        return parsed_fields.get('submitter', '')

    def parse_authors(self, parsed_fields):
        return parsed_fields.get('submitter', '')

    def generate_urls(self, parsed_fields):
        return {}

    def parse(self, message):
        try:
            return self.parse_message(message)
        except Exception as e:
            logger.warn(f'Unable to parse Message {message.id} with parser {self}: {e}')
            return False
