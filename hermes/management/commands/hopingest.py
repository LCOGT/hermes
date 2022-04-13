import json
from  datetime import datetime, timezone
import logging

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

from hop import Stream
from hop.auth import Auth
from hop.io import StartPosition, Metadata
from hop.models import GCNCircular


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
        logger.info(f'args: {args} ; kwargs: {options}')
        logger.info(f'settings: {settings}')

        with Stream().open('kafka://kafka.scimma.org/sys.heartbeat', 'r') as src:
            alert_limit = 3
            for alert in src.read():  # type(alert) is <class 'dict'>
                # decode the timestamp and insert into the alert dictionary
                t = datetime.fromtimestamp(alert["timestamp"]/1e6, tz=timezone.utc)
                alert['utc_time_iso'] = t.isoformat()
                logging.info(f'{alert_limit}: alert: {alert}')

                # topic: sys.heartbeat
                # alert = {
                #     'timestamp': 1649786674706769,
                #     'count': 48120,
                #     'beat': 'listen',
                #     'utc_time_iso': '2022-04-12T18:04:34.706769+00:00'
                # }
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


                alert_limit -= 1
                if alert_limit< 0:
                    break
