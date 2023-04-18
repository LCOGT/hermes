from django.core.management.base import BaseCommand
from django.utils import timezone
from dateutil.parser import parse
from copy import deepcopy
from hermes.models import Message
from hermes.parsers import GCNLVCCounterpartNoticeParser, GCNCircularParser, IGWNAlertParser

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

BASE_LVC_COUNTERPART = 'TITLE:            GCN/LVC COUNTERPART NOTICE\nNOTICE_DATE:      {published}\nNOTICE_TYPE:      Injected {type}\nCNTRPART_RA:      {target_ra}d +19h 59m 32.4s (J2000),\n       300.0523d +20h 00m 12.5s (current),\n      299.4524d +19h 57m 48.5s (1950)\nCNTRPART_DEC:     {target_dec}d +40d 43 51.6 (J2000),\n   +40.7847d +40d 47 04.9 (current),\n    +40.5932d +40d 35 35.4 (1950)\nCNTRPART_ERROR:   7.6 [arcsec, radius]\nEVENT_TRIG_NUM:   {event_id}\nEVENT_DATE:       18599 TJD;   116 DOY;   2019/04/26 (yy/mm/dd)\nEVENT_TIME:       55315.00 SOD (15:21:55.00) UT\nOBS_DATE:         18599 TJD;   116 DOY;   19/04/26\nOBS_TIME:         73448.0 SOD (20:24:08.00) UT\nOBS_DUR:          72.7 [sec]\nINTENSITY:        1.00e-11 +/- 2.00e-12 [erg/cm2/sec]\nENERGY:           0.3-10 [keV]\nTELESCOPE:        Swift-XRT\nSOURCE_SERNUM:    {source_sernum}\nRANK:             2\nWARN_FLAG:        0\nSUBMITTER:        {author}\nSUN_POSTN:         34.11d (+02h 16m 26s)  +13.66d (+13d 39 45)\nSUN_DIST:          84.13 [deg]   Sun_angle= 6.3 [hr] (West of Sun)\nMOON_POSTN:       309.58d (+20h 38m 19s)  -19.92d (-19d 55 00)\nMOON_DIST:         61.34 [deg]\nMOON_ILLUM:       50 [%]\nGAL_COORDS:        76.19,  5.74 [deg] galactic lon,lat of the counterpart\nECL_COORDS:       317.73, 59.32 [deg] ecliptic lon,lat of the counterpart\nCOMMENTS:         LVC Counterpart.\nCOMMENTS:         This matches a catalogued X-ray source: 1RXH J195932.6+404351\nCOMMENTS:         This source has been given a rank of 2\nCOMMENTS:         Ranks indicate how likely the object is to be\nCOMMENTS:         the GW counterpart. Ranks go from 1-4 with\nCOMMENTS:         1 being the most likely and 4 the least.\nCOMMENTS:         See http://www.swift.ac.uk/ranks.php for details.\nCOMMENTS:         MAY match a known transient, will be checked manually.'
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
        parser.add_argument('-t', '--type', choices=['LVC_INITIAL', 'LVC_PRELIMINARY', 'LVC_UPDATE', 'LVC_RETRACTION', 'LVC_COUNTERPART', 'GCN_CIRCULAR'], required=True, help='Type of injected message')
        parser.add_argument('-e', '--event_id', required=False, default='MS123456', help='NonlocalizedEventId for this message to be associated with.')
        parser.add_argument('-p', '--published', required=False, default=timezone.now().isoformat(), help='Published datetime for this Message')
        parser.add_argument('--sequence_number', required=False, default=1, help='Sequence number of injected message, only applies to LVC events.')
        parser.add_argument('--title', required=False, default='Injected Message', help='Title of injected message.')
        parser.add_argument('--skymap_version', required=False, default=-1, help='Version of the skymap associated with this sequence of an LVK alert')
        parser.add_argument('--combined_skymap_version', required=False, default=-1, help='Version of the combined skymap associated with this sequence of an LVK alert')
        parser.add_argument('--source_sernum', required=False, default=1, help='Sernum of target for LCV_COUNTERPART message.')
        parser.add_argument('--target_name', required=False, default='', help='Name of target to associate with message.')
        parser.add_argument('--target_ra', required=False, default=22.2, help='RA of target to associate with message.')
        parser.add_argument('--target_dec', required=False, default=33.3, help='DEC of target to associate with message.')

    def handle(self, *args, **options):
        logger.info(f"Injecting test message of type: {options.get('type')}")
        if options.get('type') == 'LVC_COUNTERPART':
            message_text = BASE_LVC_COUNTERPART.format(
                published=options.get('published'),
                event_id=options.get('event_id'),
                source_sernum=options.get('source_sernum'),
                author=options.get('author'),
                target_ra=options.get('target_ra'),
                target_dec=options.get('target_dec'),
                type=options.get('type')
            )
            message, _ = Message.objects.get_or_create(
                topic=options.get('type'),
                message_text=message_text,
                defaults={
                    'authors': options.get('author'),
                    'submitter': 'inject_message command'
                }
            )
            GCNLVCCounterpartNoticeParser().parse(message)
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
            title = f"{options.get('superevent_id')} - {base_type}"
            message, _ = Message.objects.get_or_create(
                topic=options.get('type'),
                title=title,
                data=message_payload,
                published=parse(options.get('published')),
                defaults={
                    'submitter': 'inject_message command',
                    'authors': options.get('author')
                }
            )
            IGWNAlertParser().parse(message)
        elif options.get('type') == 'GCN_CIRCULAR':
            header = deepcopy(BASE_GCN_CIRCULAR['header'])
            header['subject'] = header['subject'].format(event_id=options.get('event_id'))
            header['date'] = header['date'].format(published=options.get('published'))
            header['from'] = header['from'].format(author=options.get('author'))
            message, _ = Message.objects.get_or_create(
                topic=options.get('type'),
                submitter='inject_message command',
                authors=options.get('author'),
                published=parse(options.get('published')),
                title=header['subject'],
                message_text=BASE_GCN_CIRCULAR['body'],
                data=header
            )
            GCNCircularParser().parse(message)
