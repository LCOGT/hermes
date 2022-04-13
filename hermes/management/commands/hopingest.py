from fileinput import hook_encoded
import json
from  datetime import datetime, timezone
import logging
import os
from turtle import st

from django.core.management.base import BaseCommand, CommandError
#from django.conf import settings

from hop import Stream
from hop.auth import Auth
from hop.io import StartPosition, Metadata
from hop.models import GCNCircular

from hermes.models import Message

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Start a hop-client consuming messages from hop'

    def add_arguments(self, parser):
        # parser is an argparse.ArguementParser
        parser.add_argument('-u', '--username', required=False, help='Username for hop-client from scimma-admin')
        parser.add_argument('-p', '--password', required=False, help='Password for hop-client from scimma-admin')
        parser.add_argument('-t', '--test', required=False, default=False, action='store_true',
                            help='Log four sys.heartbeat gcn_circulars and exit')
        parser.add_argument('-e', '--earliest', required=False, default=False, action='store_true',
                            help='Read from the start of the Kafka stream with hop.io.StartPosition.EARLIEST')

    def _get_hop_authentication(self, options):
        """Get username and password and configure Hop client authentication

        If command line arguments are supplied, use them.
        Otherwise, get HOP_USERNAME and HOP_PASSWORD from environment.

        For the moment, since there is not yet user account support,
        HOP_USERNAME and HOP_PASSWORD should be set to enter the environment
        up as k8s secrets.
        """
        username = options.get('username')
        if username is None:
            username = os.getenv('HOP_USERNAME', None)
        password = options.get('password')
        if password is None:
            password = os.getenv('HOP_PASSWORD', None)

        if username is None or password is None:
            error_message = 'Supply Hop credentials on command line or set HOP_USERNAME and HOP_PASSWORD environment variables.'
            logger.error(error_message)
            raise CommandError(error_message)

        return Auth(username, password)


    def handle(self, *args, **options):
        logger.info(f'args: {args}')
        logger.info(f'options: {options}')

        # interpret command line options
        hop_auth = self._get_hop_authentication(options)
        if options['test']:
            logger.info('testing...')
            self._test_sys_heartbeat(hop_auth)
            exit()

        start_position = StartPosition.LATEST
        if options['earliest']:
            start_position = StartPosition.EARLIEST
        logger.info(f'hop.io.StartPosition set to {start_position}')

        #
        # GCN Circulars
        #

        # instanciate the Stream in a way that sets the io.StartPosition
        stream = Stream(auth=hop_auth, start_at=start_position)
        with stream.open('kafka://kafka.scimma.org/gcn.circular', 'r') as src:
            limit = 1
            for gcn_circular, metadata in src.read(metadata=True):
                # type(gcn_circular) is <hop.models.GNCCircular>
                # type(metadata) is <hop.io.Metadata>

                # first, what does a gcn.circular look like:
                # logging.info(f'{limit}: type(gcn_circular): {type(gcn_circular)}')
                # logging.info(f'{limit}: repr(gcn_circular): {repr(gcn_circular)}')
                # logging.info(f'{limit}: gcn_circular.asdict(): {gcn_circular.asdict()}')
                # logging.info(f'{limit}: metadata: {metadata}')

                self._update_db_with_gcn_circular(gcn_circular, metadata)

                limit -= 1
                if limit <= 0:
                    break

                # hop.models.GCNCircular(
                #     header = {
                #         'title': 'GCN CIRCULAR',
                #         'number': '31806',
                #         'subject': 'GRB 220330A: Fermi GBM Final Real-time Localization',
                #         'date': '22/03/30 12:38:33 GMT',
                #         'from': 'Fermi GBM Team at MSFC/Fermi-GBM  <do_not_reply@GIOC.nsstc.nasa.gov>'
                #         },
                #     body="""The Fermi GBM team reports the detection of a likely SHORT GRB\n\n
                #     At 12:28:09 UT on 30 Mar 2022, the Fermi Gamma-ray Burst Monitor (GBM) triggered
                #     and located GRB 220330A (trigger 670336094.273364 / 220330520).\n\n
                #     The on-ground calculated location, using the Fermi GBM trigger data,
                #     is RA = 324.1, Dec = 63.1 (J2000 degrees, equivalent to J2000 21h 36m, 63d 06'),
                #     with a statistical uncertainty of 3.8 degrees.\n\nThe angle from the Fermi LAT 
                #     boresight is 28.0 degrees.\n\n
                #     The skymap can be found here:\nhttps://heasarc.gsfc.nasa.gov/FTP/fermi/data/gbm/triggers/2022/bn220330520/quicklook/glg_skymap_all_bn220330520.png\n\nThe HEALPix FITS file, including the estimated localization systematic, can be found here:\nhttps://heasarc.gsfc.nasa.gov/FTP/fermi/data/gbm/triggers/2022/bn220330520/quicklook/glg_healpix_all_bn220330520.fit\n\nThe GBM light curve can be found here:\nhttps://heasarc.gsfc.nasa.gov/FTP/fermi/data/gbm/triggers/2022/bn220330520/quicklook/glg_lc_medres34_bn220330520.gif\n\n
                #     """
                # )

        #
        # GCN Notices
        #

        # at the moment there are no GCN Notices in hopskotch

        # instanciate the Stream in a way that sets the io.StartPosition
        # stream = Stream(start_at=start_position)
        # with stream.open('kafka://kafka.scimma.org/gcn.notice', 'r') as src:
        #     limit = 1
        #     for gcn_notice, metadata in src.read(metadata=True):
        #         # decode the timestamp and insert into the gcn_circular dictionary
        #         t = datetime.fromtimestamp(gcn_notice["timestamp"]/1e6, tz=timezone.utc)
        #         gcn_notice['utc_time_iso'] = t.isoformat()
 
        #         # first, what does a gcn.notice look like:
        #         # logging.info(f'{limit}: type(gcn_notice): {type(gcn_notice)}')
        #         # logging.info(f'{limit}: repr(gcn_notice): {repr(gcn_notice)}')
        #         # logging.info(f'{limit}: gcn_notice: {gcn_notice}')
        #         # logging.info(f'{limit}: metadata: {metadata}')

        #         limit -= 1
        #         if limit <= 0:
        #             break


    def _test_sys_heartbeat(self, auth):
        topic = 'sys.heartbeat'
        stream = Stream(auth=auth)
        with stream.open(f'kafka://kafka.scimma.org/{topic}', 'r') as src:
            limit = 3
            for hearbeat, metadata in src.read(metadata=True):
                # decode the timestamp and insert into the gcn_circular dictionary
                t = datetime.fromtimestamp(hearbeat["timestamp"]/1e6, tz=timezone.utc)
                hearbeat['utc_time_iso'] = t.isoformat()

                logging.info(f'{limit}: heartbeat: {hearbeat}')
                logging.info(f'{limit}: metadata: {metadata}')

                limit -= 1
                if limit <= 0:
                    break

                # heartbeat =  {
                #     'timestamp': 1649861479186756,
                #     'count': 22798,
                #     'beat': 'LISTEN',
                #     'utc_time_iso': '2022-04-13T14:51:19.186756+00:00'
                # }
                # hop.io.Metadata(
                #     topic='sys.heartbeat',
                #     partition=6,
                #     offset=2106694,
                #     timestamp=1649861479186,
                #     key=None,
                #     headers=None,
                #     _raw=<cimpl.Message object at 0x7f1a22d8cec0>)


    def _update_db_with_gcn_circular(self, gcn_circular, metadata):
        logger.info(f'updating db with gcn_circular number {gcn_circular.header["number"]}')
        id, created = Message.objects.update_or_create()