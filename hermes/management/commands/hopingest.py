from  datetime import datetime, timezone
import logging
import os

from django.core.management.base import BaseCommand, CommandError
#from django.conf import settings

from hop import Stream
from hop.auth import Auth
from hop.io import StartPosition, Metadata, list_topics
from hop.models import GCNCircular, JSONBlob

from hermes.brokers import hopskotch
from hermes.models import Message

logger = logging.getLogger(__name__)
#logger.setLevel(logging.DEBUG)

class UpdateTopicsException(Exception):
    pass

SCIMMA_KAFKA_URL = 'kafka://kafka.scimma.org/'

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
        parser.add_argument('-P', '--public', required=False, default=False, action='store_true',
                            help='Ingest all the publicly_readable topics.')


    def _get_scram_credential(self):
        """Get username and password from options or environment.

        If command line arguments are supplied, use them.
        Otherwise, get HERMES_INGEST_USERNAME and HERMES_INGEST_PASSWORD from environment.
        HERMES_INGEST_USERNAME and HERMES_INGEST_PASSWORD should be enter the environment as k8s secrets.
        """
        username = self.options.get('username')
        if username is None:
            username = os.getenv('HERMES_INGEST_USERNAME', None)
        password = self.options.get('password')
        if password is None:
            password = os.getenv('HERMES_INGEST_PASSWORD', None)

        if username is None or password is None:
            error_message = ('Supply Hop credentials on command line or set HERMES_INGEST_USERNAME'
                             ' and HERMES_PASSWORD environment variables.')
            logger.error(error_message)
            raise CommandError(error_message)

        return username, password


    def _init_scimma_access(self):
        """Get and saves SCiMMA Auth access information.

          * API Token: api_token
          * hop.auth.Auth instance: hop_auth
        """
        username, password = self._get_scram_credential()
        self.api_token = hopskotch.get_hermes_api_token(username, password)
        self.hop_auth = Auth(username, password)


    def _construct_topic_list(self) -> list[str]:
        """Returns the up-to-date list of Topic names to consume.

        Use the saved options to repeatedly construct the topic list, and
        keep it in sync with the publicaly_readable topics from SCiMMA Auth.

        The Topic list is a combination of the
          a. the publicly_readable Topics from SCiMMA Auth
          b. any topics supplied on the command line via -T, --topic
        """
        if self.options['public']:
            logger.info('getting publicly_readable topics from SCiMMA Auth.')
            # use the hop-client to ask Kafka directly for the topics since SCiMMA Auth can be out of sync
            # include only topics that a) contain a '.'; b) don't start with '__' (excludes __consumer_offsets)
            publicly_readable_topics = [topic for topic in list_topics(SCIMMA_KAFKA_URL, self.hop_auth).keys()
                                        if not (topic.startswith('__') and (topic.count('.')==0))]
            logger.info(f'publicly_readable_topics: {publicly_readable_topics}')
        else:
            publicly_readable_topics = []  # for when we combine with -T topics below

        logger.debug(f"options['topic']: {self.options['topic']}")
        if self.options['topic'] is None:
            extra_topics = ['sys.heartbeat'] # default defined here
        else:
            extra_topics = self.options['topic'][0] # repeatable parser arg is list of lists
        logger.debug(f'extra_topics list: {extra_topics}')

        topics_to_ingest = list(set(publicly_readable_topics + extra_topics))  # remove any duplicates

        return topics_to_ingest


    def _construct_alert_handler(self, topics) -> dict:
        """Set up and return the alert_handler dictionary.

        The alert_handler dictionary is keyed by topic name and it's values are
        callables with Hopskotch-specific signitures:
            def handle_the_hopskotch_alert(alert: hop.models.JSONBlob, metadata: hop.models.Metadata)
        or
            def handle_the_gcn_circular(alert: hop.models.GCNCircular, metadata: hop.models.Metadata)

        (hop.models.JSONBlob and hop.models.GCNCircular are the only Hopskotch alert types that I know about).

        Hermes-published alerts are hop.models.JSONBlobs with specific `content` dictionary keys and so use a
        Hermes-specific alert_handler which understands those keys.

        For alerts from arbitary topics where we have no knowledge of the content keys, we use a generic
        hander. This handler is set up to be the default in the defaultdict that we return.
        """
        alert_handler = {}
        for topic in topics:
            # set up the default alert_handler for all topics
            alert_handler[topic] = self._update_db_with_alert

            # set up specific handlers for some topics
            if topic.startswith('hermes.'):
                alert_handler[topic] = self._update_db_with_hermes_alert
            elif topic == 'sys.heartbeat-cit':
                # ignore this topic
                alert_handler['sys.heartbeat-cit'] = self._hopskotch_alert_noop
            elif topic == 'sys.heartbeat':
                alert_handler[topic] = self._heartbeat_handler

        # now, overwrite specific alert_handers for topics we know about a priori
        alert_handler['gcn.circular'] = self._update_db_with_gcn_circular
        alert_handler['gcn.notice'] = self._update_db_with_gcn_notice
        alert_handler['tomtoolkit.test'] = self._update_db_with_hermes_alert

        logger.debug(f'alert_handler: {alert_handler}')
        return alert_handler


    def handle(self, *args, **options):
        logger.debug(f'args: {args}')
        logger.debug(f'options: {options}')

        # save the options for when we refresh the stream topics
        self.options = options
        self._init_scimma_access() # get and save hop_auth and api_token

        # interpret command line options
        if options['test']:
            logger.info('testing...')
            self._test_sys_heartbeat(self.hop_auth)
            exit()

        start_position = StartPosition.LATEST
        if options['earliest']:
            start_position = StartPosition.EARLIEST
        logger.info(f'hop.io.StartPosition set to {start_position}')

        # instanciate the Stream in a way that sets the io.StartPosition
        stream = Stream(auth=self.hop_auth, start_at=start_position)

        while True:
            topics_to_ingest = self._construct_topic_list()
            # construct the alert_handler, the map from topic to alert parser/db-updater
            # for alerts on that topic
            alert_handler = self._construct_alert_handler(topics_to_ingest)
            logger.info(f'topics_to_ingest: {topics_to_ingest}')

            stream_url = f'{SCIMMA_KAFKA_URL}{",".join(topics_to_ingest)}'
            logger.debug(f'stream_url:  {stream_url}')
            # open for read ('r') returns a hop.io.Consumer instance
            with stream.open(stream_url, 'r') as consumer:
                for alert, metadata in consumer.read(metadata=True):
                    # type(gcn_circular) is <hop.models.GNCCircular>
                    # type(metadata) is <hop.io.Metadata>
                    try:
                        alert_handler[metadata.topic](alert, metadata)
                    except UpdateTopicsException:
                        break  # out of the for...consumer.read loop


    def _heartbeat_handler(self, heartbeat: JSONBlob,  metadata: Metadata):
        """The hop.models.JSONBlob has a content dict with the data.

        Understands that sys.heartbeat has a content['timestamp'] and converts to datetime
        """
        heartbeat_count = heartbeat.content['count']
        isotime = datetime.fromtimestamp(heartbeat.content['timestamp']/1e6, tz=timezone.utc).isoformat()
        if heartbeat_count % 3600 == 0:
            # every hour: log the heartbeat
            logger.info(f'_heartbeat_handler at {isotime} heartbeat: {heartbeat} with metadata: {metadata}')
        elif heartbeat_count % 60 == 0:
            # every 5': check for new publicly_readable topics
            logger.info((f'_heartbeat_handler at {isotime}  triggering Public Topics update'
                         f' on {metadata.topic} #{heartbeat_count}.'))
            raise UpdateTopicsException


    def _hopskotch_alert_logger(self, alert: JSONBlob,  metadata: Metadata):
        """The hop.models.JSONBlob has a content dict with the data.
        """
        logger.info(f'_hopskotch_alert_logger: {metadata.topic}  {alert}')


    def _hopskotch_alert_noop(self, alert: JSONBlob,  metadata: Metadata):
        """Do nothing with this alert.
        """
        pass


    def _update_db_with_gcn_circular(self, gcn_circular: GCNCircular, metadata: Metadata):
        """Add GNC Circular to Message db table (unless it already exists)

        hop.models.GCNCircular field mapping to hermes.models.Message:
        metadata.topic --> topic
        subject        --> title
        from           --> author
        body           --> message_text

        The topic and body fields will be used to query the database for the Message
        prior to creation in update_or_create()

        """
        logger.info(f'updating db with gcn_circular number {gcn_circular.header["number"]}')

        message, created = Message.objects.update_or_create(
            # fields to be compared to find existing Message (if any)
            topic=metadata.topic,
            message_text=gcn_circular.body,
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


    def _update_db_with_gcn_notice(self, alert: JSONBlob,  metadata: Metadata):
        """Ingest a GCN Notice.

        GCN Notice keypath mapping to hermes.models.Message:
        metadata.topic           --> topic
        role: Description        --> title
        Who.Author.contactName   --> author

        The topic and body fields will be used to query the database for the Message
        prior to creation in update_or_create()
        """
        logger.info(f'updating db with gcn_notice metadata: {metadata}')
        logger.info(f'updating db with gcn_notice alert.content: {alert.content}')

        # extract keypath values into vars for Hermes Message fields
        contact_name: str = f"{alert.content['Who']['Author']['contactName']}"
        try:
            contact_email: str = f" <{alert.content['Who']['Author']['contactEmail']}>"
        except KeyError:
            contact_email = ''
        author = contact_name + contact_email

        role: str = alert.content['role']
        title: str = alert.content['Description']
        if not title:
            title = "<no Description specified>"
        if role == 'test':
            title: str = f'[{role}]: {title}'

        logger.info(f'updating db with gcn_notice author: {author}')
        logger.info(f'updating db with gcn_notice title: {title}')

        message, created = Message.objects.update_or_create(
            # fields to be compared to find existing Message (if any)
            topic=metadata.topic,
            data=alert.content,
            # fields to be used to update existing or create new Message
            defaults={
                'author': author,
                'title': title,
                'message_text': "Note added by Hermes: Please Show JSON or Additional Data Table for details."
            }
        )

        if created:
            logger.info(f'created new Message with id: {message.id}')
        else:
            logger.info(f'found existing Message with id: {message.id}')
            # TODO: assert GCN Circular Number fields matches


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


    def _update_db_with_alert(self, alert: JSONBlob,  metadata: Metadata):
        """Ingest a generic  alert from a topic we have no a priori knowledge of.
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


