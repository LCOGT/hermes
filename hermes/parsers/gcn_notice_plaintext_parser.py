import logging

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

    def parse_message(self, message, data):
        if data and all(x.lower() in data.get('title', '').lower() for x in ['GCN', 'NOTICE']):
            self.link_message(message, data)
            return True
        return False

    def link_message(self, message, data):
        ''' Attempt to link or create extra models to relate targets or nonlocalized events to this message
        '''
        if not data:
            return
        event_id = ''
        if 'event_trig_num' in data:
            event_id = data['event_trig_num']
        # TODO: enable this once GRB events are being injested to support GRB_COUNTERPARTS
        # elif 'trigger_num' in message.data:
        #     event_id = message.data['trigger_num']
        if event_id:
            nonlocalizedevent, _ = NonLocalizedEvent.objects.get_or_create(event_id = event_id)
            if not nonlocalizedevent.references.contains(message):
                nonlocalizedevent.references.add(message)
                nonlocalizedevent.save()
        # Now parse the target as well
        target_name, ra, dec = self.parse_target(data, event_id)
        if target_name and ra and dec:
            target, _ = Target.objects.get_or_create(name=target_name, coordinate=Point(float(ra), float(dec), srid=4035))
            if not target.messages.contains(message):
                target.messages.add(message)
                target.save()

    def parse(self, message, data):
        try:
            return self.parse_message(message, data)
        except Exception as e:
            logger.warn(f'Unable to parse Message {message.id} with parser {self}: {e}')
            return False
