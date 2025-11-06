''' This class defines a message handler for a tom_alertstreams connection to hop streams.
'''
from datetime import datetime, timezone
from dateutil.parser import parse, parserinfo
import logging
import uuid
import numpy as np
import astropy_healpix as ah
import hashlib
from astropy import units as u
from astropy.table import Table
from io import BytesIO
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from hop.io import Metadata
from hop.models import JSONBlob, GCNTextNotice

from hermes.models import Message, NonLocalizedEvent
from hermes import parsers

logger = logging.getLogger(__name__)

GENERIC_GCN_NOTICE_PARSER = parsers.GCNNoticePlaintextParser()
GCN_TOPICS_TO_PARSERS = {
    'ICECUBE_ASTROTRACK_GOLD': parsers.IcecubeNoticePlaintextParser(),
    'ICECUBE_ASTROTRACK_BRONZE': parsers.IcecubeNoticePlaintextParser(),
    'ICECUBE_CASCADE': parsers.IcecubeNoticePlaintextParser(),
}

GCN_CIRCULAR_PARSER = parsers.GCNCircularParser()
HERMES_PARSER = parsers.HermesMessageParser()
IGWN_ALERT_PARSER = parsers.IGWNAlertParser()

TOPIC_PIECES_TO_IGNORE = [
    'gcn.notice',
    'heartbeat'
]


def generate_skymap_url(superevent_id: str, pipeline: str, skymap_version: int, combined: bool) -> str:
    """ This attempts to generate the gracedb skymap url to download the skymap later based on its
        pipeline and version.
    """
    base_url = f"https://gracedb.ligo.org/api/superevents/{superevent_id}/files/"
    if pipeline in ['pycbc', 'gstlal', 'MBTA', 'MBTAOnline', 'spiir']:
        if combined:
            return f"{base_url}combined-ext.multiorder.fits,{skymap_version}"
        else:
            return f"{base_url}bayestar.multiorder.fits,{skymap_version}"
    elif pipeline == 'CWB' and not combined:
        return f"{base_url}cwb.multiorder.fits,{skymap_version}"
    elif pipeline == 'oLIB' and not combined:
        return f"{base_url}olib.multiorder.fits,{skymap_version}"
    # Currently don't know naming scheme for mLY pipeline or combined files for CWB, oLIB or mLY
    # So just default to having no url stored rather than a wrong one.
    return None


def should_ingest_topic(topic):
    if 'test' in topic.lower() and not settings.SAVE_TEST_MESSAGES:
        return False
    for topic_piece in TOPIC_PIECES_TO_IGNORE:
        if topic_piece in topic.lower():
            return False
    return True


def get_sequence_number(superevent_id: str) -> int:
    """ This returns the sequence number of the next sequence for a superevent_id. This is a hack to get
        around the fact that IGWN GWAlerts no longer tell you the sequence number within them.
    """
    try:
        nle = NonLocalizedEvent.objects.get(event_id=superevent_id)
        return nle.sequences.count() + 1
    except NonLocalizedEvent.DoesNotExist:
        return 1  # The nonlocalizedevent doesnt exist in our system yet, so this must be the first sequence


def get_skymap_version(superevent_id: str, skymap_hash: uuid) -> int:
    """ This method gets the most recent previous sequence of this superevent and checks if the skymap has changed.
        It returns the 'version' of the skymap, which can be used to retrieve the proper file and image files from gracedb.
        This is a hack because IGWN GWAlerts no longer have any way of knowing which skymap version they reference.
    """
    try:
        nle = NonLocalizedEvent.objects.get(event_id=superevent_id)
        latest_sequence = nle.sequences.last()
        if latest_sequence == None or latest_sequence.data.get('event', {}).get('skymap_version') == None or latest_sequence.data.get('event', {}).get('skymap_hash') == None:
            return 0
        if latest_sequence.data['event']['skymap_version'] != None and latest_sequence.data['event']['skymap_hash'] != skymap_hash:
            return latest_sequence.data['event']['skymap_version'] + 1
        if latest_sequence.data['event']['skymap_version']:
            return latest_sequence.data['event']['skymap_version']
        return 0
    except NonLocalizedEvent.DoesNotExist:
        return 0  # The nonlocalizedevent doesnt exist in our system yet, so this must be the first skymap version


def get_combined_skymap_version(superevent_id: str, skymap_hash: uuid) -> int:
    """ This method looks through the most recent previous sequences of this superevent and checks if the combined_skymap has changed.
        It returns the 'version' of the skymap, which can be used to retrieve the proper file and image files from gracedb.
        This is a hack because IGWN GWAlerts no longer have any way of knowing which skymap version they reference.
    """
    try:
        nle = NonLocalizedEvent.objects.get(event_id=superevent_id)
        for sequence in nle.sequences.all().reverse():
            combined_skymap_version = sequence.data.get('external_coinc', {}).get('combined_skymap_version')
            combined_skymap_hash = sequence.data.get('external_coinc', {}).get('combined_skymap_hash')
            if combined_skymap_version != None and combined_skymap_hash and combined_skymap_hash != skymap_hash:
                return combined_skymap_version + 1
        return 0  # No previous combined_skymaps were found, so this must be the first sequence with a combined skymap
    except NonLocalizedEvent.DoesNotExist:
        return 0  # The nonlocalizedevent doesnt exist in our system yet, so this must be the first combined skymap version


def get_confidence_regions(skymap: Table):
    """ This helper method takes in the astropy Table skymap and attempts to parse out
        the 50 and 90 area confidence values. It returns a tuple of (area_50, area_90).
        See https://emfollow.docs.ligo.org/userguide/tutorial/multiorder_skymaps.html.
    """
    try:
        # Sort the pixels of the sky map by descending probability density
        skymap.sort('PROBDENSITY', reverse=True)
        # Find the area of each pixel
        level, _ = ah.uniq_to_level_ipix(skymap['UNIQ'])
        pixel_area = ah.nside_to_pixel_area(ah.level_to_nside(level))
        # Calculate the probability within each pixel: the pixel area times the probability density
        prob = pixel_area * skymap['PROBDENSITY']
        # Calculate the cumulative sum of the probability
        cumprob = np.cumsum(prob)
        # Find the pixel for which the probability sums to 0.5 (0.9)
        index_50 = cumprob.searchsorted(0.5)
        index_90 = cumprob.searchsorted(0.9)
        # The area of the 50% (90%) credible region is simply the sum of the areas of the pixels up to that probability
        area_50 = pixel_area[:index_50].sum().to_value(u.deg ** 2.)
        area_90 = pixel_area[:index_90].sum().to_value(u.deg ** 2.)

        return area_50, area_90
    except Exception as e:
        logger.error(f'Unable to parse raw skymap for OBJECT {skymap.meta["OBJECT"]} for confidence regions: {e}')

    return None, None


def get_sender_from_metadata(metadata: Metadata) -> str:
    """ Extract a string sender from the message metadata
    """
    # get the tuple with the sender: key is '_sender'
    sender_tuple = next((item for item in metadata.headers if item[0] == '_sender'), None)
    if sender_tuple:
        return sender_tuple[1].decode()
    return ''


def get_or_create_uuid_from_metadata(metadata: Metadata) -> uuid.UUID:
    """Extract the UUID from the message metadata, or generate a UUID if none present in metadata.

    The headers property of the metadata is a list of tuples of the form [('key', value), ...].
    """
    # get the tuple with the uuid: key is '_id'
    message_uuid_tuple = None
    if metadata.headers:
        message_uuid_tuple = next((item for item in metadata.headers if item[0] == '_id'), None)
    if message_uuid_tuple:
        message_uuid = uuid.UUID(bytes=message_uuid_tuple[1])
    else:
        # this message header metadata didn't have UUID, so make one
        message_uuid = uuid.uuid4()
    return message_uuid


def ignore_message(blob: JSONBlob, metadata: Metadata):
    """ Ignore the message sent here
    """
    return


def handle_generic_message(blob: JSONBlob, metadata: Metadata):
    """Ingest a generic  alert from a topic we have no a priori knowledge of.
    """
    topic = metadata.topic
    logger.warning(f"Handling message on topic {topic}")
    if topic == 'sys.heartbeat-cit':
        # Store the last timestamp we received a heartbeat message to know if the stream is alive
        cache.set('hop_stream_heartbeat', timezone.now().isoformat(), None)
    if should_ingest_topic(topic):
        logger.debug(f'updating db with generic hop message for topic {topic}')
        try:
            message, created = Message.objects.get_or_create(
                uuid=get_or_create_uuid_from_metadata(metadata)
            )
            if created:
                logger.debug(f'created new Message with id: {message.id} and uuid: {message.uuid}')
            else:
                logger.debug(f'found existing Message with and uuid: {message.uuid} id: {message.id}')
        except Exception as ex:
            logger.warning(f"Failed to ingest message from topic {topic}: {repr(ex)}")


def handle_gcn_notice_message(notice: GCNTextNotice, metadata: Metadata):
    """Ingest a gcn plaintext notice through the hop stream.
    """
    topic = metadata.topic
    logger.warning(f"Handling message on topic {topic}")
    if should_ingest_topic(topic):
        logger.debug(f'updating db with gcn text notice hop message for topic {topic}')
        # metadata.timestamp is the number of milliseconds since the epoch (UTC).
        try:
            message, created = Message.objects.get_or_create(
                uuid=get_or_create_uuid_from_metadata(metadata),
            )
            if created:
                logger.debug(f'created new Message with id: {message.id} and uuid: {message.uuid}')
            else:
                logger.debug(f'found existing Message with and uuid: {message.uuid} id: {message.id}')
        except Exception as ex:
            logger.warning(f"Failed to ingest message from topic {topic}: {repr(ex)}")

        # See if any of the specific parsers match a piece of the topic
        for topic_piece, parser in GCN_TOPICS_TO_PARSERS.items():
            if topic_piece in topic.upper():
                parser.parse(message, notice.fields)
                return
        # If none of the topic pieces for more specific parsers match, then just use the generic gcn notice parser
        GENERIC_GCN_NOTICE_PARSER.parse(message, notice.fields)


def handle_gcn_circular_message(gcn_circular: JSONBlob, metadata: Metadata):
    """Add GNC Circular to Message db table (unless it already exists)

    The topic and body fields will be used to query the database for the Message
    prior to creation in update_or_create()

    """
    circular = gcn_circular.content
    logger.debug(f'updating db with gcn_circular number {circular["circularId"]}')
    message, created = Message.objects.get_or_create(
        uuid=get_or_create_uuid_from_metadata(metadata),
    )
    GCN_CIRCULAR_PARSER.parse(message, circular)

    if created:
        logger.debug(f'created new Message with id: {message.id} and uuid: {message.uuid}')
    else:
        logger.debug(f'found existing Message with and uuid: {message.uuid} id: {message.id}')


def handle_igwn_message(message: JSONBlob, metadata: Metadata):
    alert = message.content[0]
    # Only store test alerts if we are configured to do so
    if alert.get('superevent_id', '').startswith('M') and not settings.SAVE_TEST_MESSAGES:
        return
    alert_uuid = get_or_create_uuid_from_metadata(metadata)

    # Here we do a bit of pre-processing for IGWN alerts in order to be able to remove the skymap before saving the file
    if alert.get('event'):
        skymap_bytes = alert['event'].pop('skymap')
        if skymap_bytes:
            skymap = Table.read(BytesIO(skymap_bytes))
            area_50, area_90 = get_confidence_regions(skymap)
            if area_50:
                alert['event']['area_50'] = area_50
                alert['event']['area_90'] = area_90
            skymap_hash = hashlib.md5(skymap_bytes)
            skymap_version = get_skymap_version(alert['superevent_id'], skymap_hash=uuid.UUID(skymap_hash.hexdigest()))
            alert['event']['skymap_hash'] = skymap_hash.hexdigest()
            alert['event']['skymap_version'] = skymap_version
            skymap_url = generate_skymap_url(alert['superevent_id'], alert['event']['pipeline'], skymap_version, False)
            if skymap_url:
                alert['urls']['skymap'] = skymap_url
    if alert.get('external_coinc', {}):
        combined_skymap_bytes = alert['external_coinc'].pop('combined_skymap')
        if combined_skymap_bytes:
            combined_skymap = Table.read(BytesIO(combined_skymap_bytes))
            area_50, area_90 = get_confidence_regions(combined_skymap)
            if area_50:
                alert['external_coinc']['area_50'] = area_50
                alert['external_coinc']['area_90'] = area_90
            combined_skymap_hash = hashlib.md5(combined_skymap_bytes)
            combined_skymap_version = get_skymap_version(alert['superevent_id'], skymap_hash=uuid.UUID(combined_skymap_hash.hexdigest()))
            alert['external_coinc']['combined_skymap_hash'] = combined_skymap_hash.hexdigest()
            alert['external_coinc']['combined_skymap_version'] = combined_skymap_version
            combined_skymap_url = generate_skymap_url(alert['superevent_id'], alert['event']['pipeline'], combined_skymap_version, True)
            if combined_skymap_url:
                alert['urls']['combined_skymap'] = combined_skymap_url
    alert['sequence_num'] = get_sequence_number(alert['superevent_id'])

    logger.debug(f"Storing message for igwn alert {alert_uuid}: {alert}")
    message, created = Message.objects.get_or_create(
        uuid=alert_uuid,
    )

    IGWN_ALERT_PARSER.parse(message, alert)

    if created:
        logger.debug(f'created new Message with id: {message.id} and uuid: {message.uuid}')
    else:
        logger.debug(f'found existing Message with and uuid: {message.uuid} id: {message.id}')


def handle_hermes_message(hermes_message: JSONBlob,  metadata: Metadata):
    """Ingest a Hermes-published alert.

    This method understands that Hermes-published alerts have the following content keys:
    'topic', 'title', 'authors', 'data', and 'message_text'.
    """
    logger.debug(f'updating db with hermes alert {hermes_message}')
    logger.debug(f'metadata: {metadata}')
    # Only store test hermes messages if we are configured to do so
    if not should_ingest_topic(hermes_message.content['topic']):
        return
    logger.warning(f"Handling message on topic {hermes_message.content['topic']}")

    message, created = Message.objects.get_or_create(
        uuid=get_or_create_uuid_from_metadata(metadata),
    )

    HERMES_PARSER.parse(message, hermes_message.content)

    if created:
        logger.debug(f'created new Message with id: {message.id} and uuid: {message.uuid}')
    else:
        logger.debug(f'found existing Message with uuid: {message.uuid} id: {message.id}')
