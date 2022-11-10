from  datetime import datetime, timezone
import logging
import os

from django.core.management.base import BaseCommand, CommandError
#from django.conf import settings

from hop import Stream
from hop.auth import Auth
from hop.io import StartPosition, Metadata
from hop.models import GCNCircular, JSONBlob

from hermes.brokers import hopskotch
from hermes.models import Message

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = """
    Start a hop-client consuming messages from hop. If both -P, --public  and -T, --topic switches
    are used together, the publicly_readable topics and the specifically named topics are all ingested.
    """

    def add_arguments(self, parser):
        # parser is an argparse.ArguementParser
        parser.add_argument('-e', '--earliest', required=False, default=False, action='store_true',
                            help='Read from the start of the Kafka stream with hop.io.StartPosition.EARLIEST')
        parser.add_argument('-T', '--topic', required=False, action='append', nargs='*',
                            help='Repeatable. Topic to ingest. Defaults to sys.heartbeat')
        parser.add_argument('-u', '--username', required=False, help='Username for hop-client from scimma-admin')
        parser.add_argument('-p', '--password', required=False, help='Password for hop-client from scimma-admin')
        parser.add_argument('-t', '--test', required=False, default=False, action='store_true',
                            help='Log four sys.heartbeat and exit')
        parser.add_argument('-P', '--public', required=False, default=True, action='store_true',
                            help='Ingest all the publicly_readable topics.')


    def _get_scram_credential(self, options):
        """Get username and password from options or environment.

        If command line arguments are supplied, use them.
        Otherwise, get HERMES_INGEST_USERNAME and HERMES_INGEST_PASSWORD from environment.
        HERMES_INGEST_USERNAME and HERMES_INGEST_PASSWORD should be enter the environment as k8s secrets.
        """
        username = options.get('username')
        if username is None:
            username = os.getenv('HERMES_INGEST_USERNAME', None)
        password = options.get('password')
        if password is None:
            password = os.getenv('HERMES_INGEST_PASSWORD', None)

        if username is None or password is None:
            error_message = ('Supply Hop credentials on command line or set HERMES_INGEST_USERNAME'
                             ' and HERMES_PASSWORD environment variables.')
            logger.error(error_message)
            raise CommandError(error_message)

        return username, password


    def _get_hop_authentication(self, username, password) -> Auth:
        return Auth(username, password)


    def _get_topic_list(self, username, password):
        api_token = hopskotch.get_hermes_api_token(username, password)
        topics = hopskotch.get_topics(api_token, publicly_readable_only=True)
        topic_names = [topic['name'] for topic in topics]
        return topic_names


    def handle(self, *args, **options):
        logger.debug(f'args: {args}')
        logger.debug(f'options: {options}')

        # interpret command line options
        username, password = self._get_scram_credential(options)
        hop_auth = self._get_hop_authentication(username, password)
        if options['test']:
            logger.info('testing...')
            self._test_sys_heartbeat(hop_auth)
            exit()

        start_position = StartPosition.LATEST
        if options['earliest']:
            start_position = StartPosition.EARLIEST
        logger.info(f'hop.io.StartPosition set to {start_position}')

        if options['public']:
            logger.info('getting publicly_readable topics from SCiMMA Auth.')
            publicly_readable_topics = self._get_topic_list(username, password)
            logger.info(f'publicly_readable_topics: {publicly_readable_topics}')

        logger.info(f"options['topic']: {options['topic']}")
        if options['topic'] is None:
            extra_topics = ['sys.heartbeat'] # default defined here
        else:
            extra_topics = options['topic'][0] # repeatable parser arg is list of lists
        logger.info(f'extra_topics list: {extra_topics}')

        topics_to_ingest = list(set(publicly_readable_topics + extra_topics))
        logger.info(f'topics_to_ingest: {topics_to_ingest}')

        # construct the alert_handler as a defaultdict from the list of topics
        # alert_handler = self._construct_alert_handler(topics_to_ingest)

        # map from topic to alert parser/db-updater for that topic
        alert_handler = {
            'tomtoolkit.test': self._update_db_with_hermes_alert,
            #'hermes.test': self._update_db_with_hermes_alert,
            'hermes.test': self._hopskotch_alert_handler,
            # Public Topics
            # TODO: get this list from the SCiMMA Auth API via hopskotch.get_topcs
            'sys.heartbeat': self._heartbeat_handler,
            'sys.heartbeat-cit': self._heartbeat_handler,
            'gcn.circular': self._hopskotch_alert_handler,
            'gcn.notice': self._hopskotch_alert_handler,
            'icecube.HE-tracks': self._hopskotch_alert_handler,
            'amon.nuem': self._hopskotch_alert_handler,
        }

        # instanciate the Stream in a way that sets the io.StartPosition
        stream = Stream(auth=hop_auth, start_at=start_position)
        stream_url = f'kafka://kafka.scimma.org/{",".join(topics_to_ingest)}'
        logger.info(f'stream_url:  {stream_url}')
        with stream.open(stream_url, 'r') as src:
            for alert, metadata in src.read(metadata=True):
                # type(gcn_circular) is <hop.models.GNCCircular>
                # type(metadata) is <hop.io.Metadata>
                alert_handler[metadata.topic](alert, metadata)


    def _heartbeat_handler(self, heartbeat: JSONBlob,  metadata: Metadata):
        """The hop.models.JSONBlob has a content dict with the data.

        Understands that sys.heartbeat has a content['timestamp'] and converts to datetime
        """
        if heartbeat.content['count'] % 3600 == 0:
            isotime = datetime.fromtimestamp(heartbeat.content['timestamp']/1e6, tz=timezone.utc).isoformat()
            logger.info(f'_heartbeat_handler at {isotime} heartbeat: {heartbeat} with metadata: {metadata}')


    def _hopskotch_alert_handler(self, alert: JSONBlob,  metadata: Metadata):
        """The hop.models.JSONBlob has a content dict with the data.
        """
        logger.info(f'_hopskotch_alert_hander: {metadata.topic}  {alert}')


    def _update_db_with_gcn_circular(self, gcn_circular, metadata):
        """Add GNC Circular to Message db table (unless it already exists)

        hop.models.GCNCircular field mapping to hermes.models.Message:
        metadata.topic --> topic
        subject        --> title
        from           --> author
        .asdict()      --> data
        body           --> message_text

        The topic and data fields will be used to query the database for the Message
        prior to creation in update_or_create()

        """
        logger.info(f'updating db with gcn_circular number {gcn_circular.header["number"]}')

        message, created = Message.objects.update_or_create(
            # fields to be compared to find existing Message (if any)
            data=gcn_circular.asdict(),
            topic=metadata.topic,
            # fields to be used to update existing or create new Message
            defaults={
                'title': gcn_circular.header['subject'],
                'author': gcn_circular.header['from'],
                'message_text': gcn_circular.body,
            }
        )

        if created:
            logger.info(f'created new Message with id: {message.id}')
        else:
            logger.info(f'found existing Message with id: {message.id}')
            # TODO: assert GCN Circular Number fields matches


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

    def _update_db_with_hermes_alert(self, hermes_alert: JSONBlob,  metadata: Metadata):
        """Ingest a Hermes-published alert.

        This method understands that Hermes-published alerts have the following content keys:
        'topic', 'title', 'author', 'data', and 'message_text'.
        """
        logger.info(f'updating db with hermes alert {hermes_alert}')
        logger.info(f'metadata: {metadata}')
        try:
            message, created = Message.objects.update_or_create(
                # all these fields must match for update...
                topic=hermes_alert.content['topic'],
                title=hermes_alert.content['title'],
                author=hermes_alert.content['author'],
                data=hermes_alert.content['data'],
                message_text=hermes_alert.content['message_text'],
            )
        except KeyError as err:
            logger.error(f'Required key ({err} not found in {metadata.topic} alert: {hermes_alert}.')
            return 

        if created:
            logger.info(f'created new Message with id: {message.id}')
        else:
            logger.info(f'found existing Message with id: {message.id}')


    def update_db_with_alert(self, alert: JSONBlob,  metadata: Metadata):
        """Ingest a Hermes-published alert.
        """
        logger.info(f'updating db with alert {alert}')
        logger.info(f'metadata: {metadata}')
        try:
            message, created = Message.objects.update_or_create(
                # these fields must match for update...
                topic=metadata.topic,
                data=alert.content,
            )
        except KeyError as err:
            logger.error(f'Required key ({err} not found in {metadata.topic} alert: {alert}.')
            return

        if created:
            logger.info(f'created new Message with id: {message.id}')
        else:
            logger.info(f'found existing Message with id: {message.id}')

        pass


    def _test_sys_heartbeat(self, auth):
        topic = 'sys.heartbeat'
        stream = Stream(auth=auth)
        with stream.open(f'kafka://kafka.scimma.org/{topic}', 'r') as src:
            limit = 3
            for heartbeat, metadata in src.read(metadata=True):
                # decode the timestamp and insert into the gcn_circular dictionary
                t = datetime.fromtimestamp(heartbeat["timestamp"]/1e6, tz=timezone.utc)
                heartbeat['utc_time_iso'] = t.isoformat()

                logging.info(f'{limit}: heartbeat: {heartbeat}')
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


