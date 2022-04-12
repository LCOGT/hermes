import json
from  datetime import datetime, timezone
import logging

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

from  hop import Stream

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Start a hop-client consuming messages from hop'

    def add_arguments(self, parser):
        pass
        #parser.add_argument('poll_ids', nargs='+', type=int)

        #parser.add_argument('username', required=False, help='Username from scimma-admin')


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

                alert_limit -= 1
                if alert_limit< 0:
                    break
