from dateutil.parser import parse
import logging
import uuid
import hashlib

from django.contrib.gis.geos import Point

from hermes.models import NonLocalizedEvent, Target, NonLocalizedEventSequence
from hermes.parsers.gcn_notice_plaintext_parser import GCNNoticePlaintextParser


logger = logging.getLogger(__name__)


class IcecubeNoticePlaintextParser(GCNNoticePlaintextParser):
    """
    This parser should work in ICECUBE GOLD/BRONZE and CASCADE alerts
    Sample GCN/AMON Notice:

    TITLE:            GCN/AMON NOTICE
    NOTICE_DATE:      Wed 23 Aug 23 08:27:06 UT
    NOTICE_TYPE:      ICECUBE Astrotrack Gold 
    STREAM:           24
    RUN_NUM:          138283
    EVENT_NUM:        14780365
    SRC_RA:           19.4330d {+01h 17m 44s} (J2000),
                      19.7270d {+01h 18m 54s} (current),
                      18.8112d {+01h 15m 15s} (1950)
    SRC_DEC:          11.4977d {-11d 29' 51"} (J2000),
                      -11.3737d {-11d 22' 24"} (current),
                      -11.7607d {-11d 45' 38"} (1950)
    SRC_ERROR:        30.80 [arcmin radius, stat-only, 90% containment]
    SRC_ERROR50:      12.00 [arcmin radius, stat-only, 50% containment]
    DISCOVERY_DATE:   20179 TJD;   235 DOY;   23/08/23 (yy/mm/dd)
    DISCOVERY_TIME:   30374 SOD {08:26:14.59} UT
    REVISION:         0
    ENERGY:           3.4127e+03 [TeV]
    SIGNALNESS:       3.2938e-01 [dn]
    FAR:              0.5131 [yr^-1]
    SUN_POSTN:        152.07d {+10h 08m 16s}  +11.48d {+11d 28' 44"}
    SUN_DIST:         133.34 [deg]   Sun_angle= 8.8 [hr] (West of Sun)
    MOON_POSTN:       224.20d {+14h 56m 49s}  -18.83d {-18d 49' 31"}
    MOON_DIST:        141.34 [deg]
    GAL_COORDS:       145.76,-73.19 [deg] galactic lon,lat of the event
    ECL_COORDS:       13.38,-18.21 [deg] ecliptic lon,lat of the event
    COMMENTS:         IceCube Gold event.  
    COMMENTS:         The position error is statistical only, there is no systematic added.
    """

    def __repr__(self):
        return 'Icecube Notice Plaintext Parser v1'

    def parse_target(self, parsed_fields, event_id):
        """ Attempt to parse out a target ra, and dec from this alert.
            Icecube alerts have the center coordinate as src_ra, src_dec.
            There is an associated radial error 90/50% in src_error and src_error50.
        """
        target_name = f"icecube_{event_id}_src"
        ra = dec = None
        try:
            raw_ra = parsed_fields['src_ra'].split(',')[0]
            raw_dec = parsed_fields['src_dec'].split(',')[0]
            ra = raw_ra.split('d', 1)[0]
            dec = raw_dec.split('d', 1)[0]
        except Exception as e:
            logger.warn(f'Unable to parse source coordinates for icecube gcn notice: {e}')
        return target_name, ra, dec

    def link_message(self, message, data):
        ''' Attempt to link or create extra models to relate targets or nonlocalized events to this message
        '''
        if not data:
            return
        event_id = ''
        if 'run_num' in data and 'event_num' in data:
            event_id = f"{data['run_num']}_{data['event_num']}"
        if event_id:
            nonlocalizedevent, _ = NonLocalizedEvent.objects.get_or_create(
                event_id = event_id, event_type=NonLocalizedEvent.NonLocalizedEventType.NEUTRINO)
            if not nonlocalizedevent.references.contains(message):
                nonlocalizedevent.references.add(message)
                nonlocalizedevent.save()

        data['urls'] = self.generate_urls(data)

        sequence_number = int(data.get('revision', 0))
        notice_type = NonLocalizedEventSequence.NonLocalizedEventSequenceType.INITIAL
        if sequence_number > 0:
            notice_type = NonLocalizedEventSequence.NonLocalizedEventSequenceType.UPDATE
        NonLocalizedEventSequence.objects.get_or_create(
            message=message, event=nonlocalizedevent, sequence_number=sequence_number, sequence_type=notice_type,
            data=data
        )

        # Now parse the center target as well
        target_name, ra, dec = self.parse_target(data, event_id)
        if target_name and ra and dec:
            target, _ = Target.objects.get_or_create(name=target_name, coordinate=Point(float(ra), float(dec), srid=4035))
            if not target.messages.contains(message):
                target.messages.add(message)
                target.save()

    def generate_urls(self, parsed_fields):
        if 'run_num' in parsed_fields and 'event_num' in parsed_fields:
            event_id = f"{parsed_fields['run_num']}_{parsed_fields['event_num']}"
            if 'cascade' in parsed_fields.get('notice_type', '').lower():
                notice_type = 'notices_amon_icecube_cascade'
            else:
                notice_type = 'notices_amon_g_b'
            return {
                'gcn': f"https://gcn.gsfc.nasa.gov/{notice_type}/{event_id}.amon"
            }
        return {}
