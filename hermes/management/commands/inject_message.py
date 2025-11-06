from django.core.management.base import BaseCommand
from django.utils import timezone
from dateutil.parser import parse
from copy import deepcopy
from hermes.models import Message
from hermes.parsers import GCNNoticePlaintextParser, GCNCircularParser, IGWNAlertParser, IcecubeNoticePlaintextParser

import uuid
import logging
logger = logging.getLogger(__name__)

BASE_LVK_MESSAGE = {
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

BASE_LVC_COUNTERPART = {
    "rank": "3",
    "title": "GCN/LVC COUNTERPART NOTICE",
    "energy": "0.3-10 [keV]",
    "obs_dur": "1632.2 [sec]",
    "comments": "LVC Counterpart.\nDetection flag was 'GOOD'  \nSignificance of fading: 0 sigma  \nThis source has been given a rank of 3  \nRanks indicate how likely the object is to be  \nthe GW counterpart. Ranks go from 1-4 with   \n1 being the most likely and 4 the least.  \nSee http://www.swift.ac.uk/ranks.php for details.",
    "obs_date": "20426 TJD;   117 DOY;   24/04/26",
    "obs_time": "44575.0 SOD {12:22:55.00} UT",
    "sun_dist": "94.58 [deg]   Sun_angle= -5.8 [hr] (East of Sun)",
    "intensity": "5.00e-13 +/- 1.30e-13 [erg/cm2/sec]",
    "moon_dist": "103.34 [deg]",
    "submitter": "Phil_Evans",
    "sun_postn": "34.70d {+02h 18m 49s}  +13.86d {+13d 51' 48\"}",
    "telescope": "Swift-XRT",
    "warn_flag": "0",
    "ecl_coords": "133.58,-48.19 [deg] ecliptic lon,lat of the counterpart",
    "event_date": "20422 TJD;   113 DOY;   2024/04/22 (yy/mm/dd)",
    "event_time": "77713.00 SOD {21:35:13.00} UT",
    "gal_coords": "247.48,  1.60 [deg] galactic lon,lat of the counterpart",
    "moon_illum": "92 [%]",
    "moon_postn": "247.00d {+16h 28m 00s}  -26.06d {-26d 03' 19\"}",
    "cntrpart_ra": "121.8573d {+08h 07m 25.7s} (J2000), 122.1038d {+08h 08m 24.9s} (current), 121.3503d {+08h 05m 24.0s} (1950)",
    "notice_date": "Fri 26 Apr 24 19:23:31 UT",
    "notice_type": "Other",
    "cntrpart_dec": "-29.4592d {-29d 27' 33.1\"} (J2000), -29.5309d {-29d 31' 51.1\"} (current), -29.3133d {-29d 18' 47.8\"} (1950)",
    "source_sernum": "255",
    "cntrpart_error": "5.0 [arcsec, radius]",
    "event_trig_num": "S240422ed"
}

BASE_ICECUBE_CASCADE = {
    "far": "0.3110 [yr^-1]",
    "title": "GCN/AMON NOTICE",
    "energy": "96.63 [TeV]",
    "src_ra": "111.9776d {+07h 27m 55s} (J2000),\n112.3027d {+07h 29m 13s} (current),\n111.3448d {+07h 25m 23s} (1950)",
    "stream": "26",
    "run_num": "141344",
    "src_dec": "-1.7676d {-01d 46' 02\"} (J2000),\n-1.8215d {-01d 49' 16\"} (current),\n-1.6648d {-01d 39' 52\"} (1950)",
    "comments": "IceCube Cascade event.\nThe position error is the combined statistical and the systematic.",
    "revision": "0",
    "sun_dist": "57.65 [deg]   Sun_angle= 3.8 [hr] (West of Sun)",
    "event_num": "29341777",
    "moon_dist": "81.12 [deg]",
    "src_error": "13.28 [deg radius, stat+systematic, 90% containment]",
    "sun_postn": "169.66d {+11h 18m 39s}   +4.45d {+04d 26' 52\"}",
    "ecl_coords": "114.05,-23.39 [deg] ecliptic lon,lat of the event",
    "event_name": "IceCubeCascade-250911a",
    "gal_coords": "218.70,  7.29 [deg] galactic lon,lat of the event",
    "moon_postn": "32.17d {+02h 08m 40s}  +17.03d {+17d 01' 59\"}",
    "signalness": "9.0012e-01 [dn]",
    "notice_date": "Thu 11 Sep 25 05:47:53 UT",
    "notice_type": "ICECUBE Cascade",
    "src_error50": "7.28 [deg radius, stat+systematic, 50% containment]",
    "discovery_date": "20929 TJD;   254 DOY;   25/09/11 (yy/mm/dd)",
    "discovery_time": "16117 SOD {04:28:37.14} UT",
    "skymap_png_url": "https://roc.icecube.wisc.edu/public/hese_cascades/hese_60929_run00141344.evt000029341777.png",
    "skymap_fits_url": "https://roc.icecube.wisc.edu/public/hese_cascades/hese_60929_run00141344.evt000029341777.fits"
}

BASE_GCN_CIRCULAR = {
    "header":
    {
        "title":"GCN CIRCULAR",
        "number":"28609",
        "subject":"{event_id}: No candidate counterparts from the Zwicky Transient Facility",
        "date":"{published}",
        "from":"{author}"
    },
    "body":"This is an injected test gcn circular message."
}

class Command(BaseCommand):
    help = 'Inject a Message into the system and attempt to parse it, given a few fields being set to mimick different message types'

    def add_arguments(self, parser):
        # parser is an argparse.ArguementParser
        parser.add_argument('-a', '--author', required=False, default='Admin', help='Author (Submitter) of injected message.')
        parser.add_argument('-t', '--type', choices=['LVC_INITIAL', 'LVC_PRELIMINARY', 'LVC_UPDATE', 'LVC_RETRACTION', 'LVC_COUNTERPART', 'GCN_CIRCULAR', 'ICECUBE_CASCADE'], required=True, help='Type of injected message')
        parser.add_argument('-e', '--event_id', required=False, default='MS123456', help='NonlocalizedEventId for this message to be associated with.')
        parser.add_argument('-p', '--published', required=False, default=timezone.now().isoformat(), help='Published datetime for this Message')
        parser.add_argument('--sequence_number', required=False, default=1, help='Sequence number of injected message, only applies to LVC events.')
        parser.add_argument('--skymap_version', required=False, default=-1, help='Version of the skymap associated with this sequence of an LVK alert')
        parser.add_argument('--combined_skymap_version', required=False, default=-1, help='Version of the combined skymap associated with this sequence of an LVK alert')
        parser.add_argument('--source_sernum', required=False, default=1, help='Sernum of target for LCV_COUNTERPART message.')
        parser.add_argument('--target_name', required=False, default='', help='Name of target to associate with message.')
        parser.add_argument('--target_ra', required=False, default=22.2, help='RA of target to associate with message.')
        parser.add_argument('--target_dec', required=False, default=33.3, help='DEC of target to associate with message.')

    def handle(self, *args, **options):
        logger.info(f"Injecting test message of type: {options.get('type')}")
        if options.get('type') == 'LVC_COUNTERPART':
            message_payload = deepcopy(BASE_LVC_COUNTERPART)
            message_payload['event_trig_num'] = options.get('event_id')
            message_payload['source_sernum'] = options.get('source_sernum')
            message_payload['cntrpart_ra'] = f"{options.get('target_ra')}d,"
            message_payload['cntrpart_dec'] = f"{options.get('target_dec')}d,"
            message = Message.objects.create()
            GCNNoticePlaintextParser().parse(message, message_payload)
        elif options.get('type') == 'ICECUBE_CASCADE':
            message_payload = deepcopy(BASE_ICECUBE_CASCADE)
            message_payload['event_num'] = options.get('event_id')
            message_payload['run_num'] = options.get('sequence_number')
            message_payload['src_ra'] = f"{options.get('target_ra')}d,"
            message_payload['src_dec'] = f"{options.get('target_dec')}d,"
            message_payload['notice_type'] = options.get('type')
            message = Message.objects.create()
            IcecubeNoticePlaintextParser().parse(message, message_payload)
        elif 'LVC' in options.get('type'):
            base_type = options.get('type').split('_')[1]
            message_payload = deepcopy(BASE_LVK_MESSAGE)
            message_payload['alert_type'] = base_type
            message_payload['superevent_id'] = options.get('event_id')
            message_payload['time_created'] = options.get('published')
            message_payload['sequence_num'] = options.get('sequence_number')
            if options.get('skymap_version') >= 0:
                message_payload['event']['skymap_version'] = options.get('skymap_version')
                message_payload['event']['skymap_hash'] = uuid.uuid4().hex
            if options.get('combined_skymap_version') >= 0:
                message_payload['external_coinc'] = {
                    'combined_skymap_version': options.get('skymap_version'),
                    'combined_skymap_hash': uuid.uuid4().hex
                }
            message = Message.objects.create()
            IGWNAlertParser().parse(message, message_payload)
        elif options.get('type') == 'GCN_CIRCULAR':
            header = deepcopy(BASE_GCN_CIRCULAR['header'])
            header['subject'] = header['subject'].format(event_id=options.get('event_id'))
            header['date'] = header['date'].format(published=options.get('published'))
            header['from'] = header['from'].format(author=options.get('author'))
            message = Message.objects.create()
            GCNCircularParser().parse(message, header)
