''' This class defines a message handler for a tom_alertstreams connection to hop streams.
'''
from datetime import datetime, timezone
from dateutil.parser import parse, parserinfo
import logging
import uuid
import fastavro
import healpy as hp
import numpy as np
import hashlib
from astropy.table import Table
from io import BytesIO
from django.conf import settings

from hop.io import Metadata
from hop.models import GCNCircular, JSONBlob

from hermes.models import Message, NonLocalizedEvent, NonLocalizedEventSequence
from hermes import parsers

logger = logging.getLogger(__name__)

GCN_CIRCULAR_PARSER = parsers.GCNCircularParser()
HERMES_PARSER = parsers.HermesMessageParser()
IGWN_ALERT_PARSER = parsers.IGWNAlertParser()

TOPIC_PIECES_TO_IGNORE = [
    'gcn.notice',
    'heartbeat'
]


def should_ingest_topic(topic):
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
        if latest_sequence.skymap_hash != skymap_hash:
            return latest_sequence.skymap_version + 1
        return latest_sequence.skymap_version
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
            if sequence.combined_skymap_version and sequence.combined_skymap_hash and sequence.combined_skymap_hash != skymap_hash:
                return sequence.combined_skymap_version + 1
        return 0  # No previous combined_skymaps were found, so this must be the first sequence with a combined skymap
    except NonLocalizedEvent.DoesNotExist:
        return 0  # The nonlocalizedevent doesnt exist in our system yet, so this must be the first combined skymap version


def get_confidence_regions(skymap: Table):
    """ This helper method takes in the astropy Table skymap and attempts to parse out
        the 50 and 90 area confidence values. It returns a tuple of (area_50, area_90).
    """
    try:
        # Get the total number of healpixels in the map
        n_pixels = len(skymap['PROBDENSITY'])
        # Covert that to the nside parameter
        nside = hp.npix2nside(n_pixels)
        # Sort the probabilities so we can do the cumulative sum on them
        probabilities = skymap['PROBDENSITY']
        probabilities.sort()
        # Reverse the list so that the largest pixels are first
        probabilities = probabilities[::-1]
        cumulative_probabilities = np.cumsum(probabilities)
        # The number of pixels in the 90 (or 50) percent range is just given by the first set of pixels that add up
        # to 0.9 (0.5)
        index_90 = np.min(np.flatnonzero(cumulative_probabilities >= 0.9))
        index_50 = np.min(np.flatnonzero(cumulative_probabilities >= 0.5))
        # Because the healpixel projection has equal area pixels, the total area is just the heal pixel area * the
        # number of heal pixels
        healpixel_area = hp.nside2pixarea(nside, degrees=True)
        area_50 = (index_50 + 1) * healpixel_area
        area_90 = (index_90 + 1) * healpixel_area

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


def handle_generic_message(message: JSONBlob, metadata: Metadata):
    """Ingest a generic  alert from a topic we have no a priori knowledge of.
    """
    topic = metadata.topic
    if should_ingest_topic(topic):
        logger.debug(f'updating db with generic hop message for topic {topic}')
        # metadata.timestamp is the number of milliseconds since the epoch (UTC).
        published_time: datetime.date = datetime.fromtimestamp(metadata.timestamp/1e3, tz=timezone.utc)
        message, created = Message.objects.update_or_create(
            # these fields must match for update...
            topic=topic,
            title='Generic Message',
            uuid=get_or_create_uuid_from_metadata(metadata),
            published=published_time,
            data=message.content
        )
        if created:
            logger.debug(f'created new Message with id: {message.id} and uuid: {message.uuid}')
        else:
            logger.debug(f'found existing Message with and uuid: {message.uuid} id: {message.id}')


def handle_gcn_circular_message(gcn_circular: GCNCircular, metadata: Metadata):
    """Add GNC Circular to Message db table (unless it already exists)

    hop.models.GCNCircular field mapping to hermes.models.Message:
    metadata.topic --> topic
    subject        --> title
    from           --> authors
    body           --> message_text

    The topic and body fields will be used to query the database for the Message
    prior to creation in update_or_create()

    """
    logger.debug(f'updating db with gcn_circular number {gcn_circular.header["number"]}')
    # published date is in the header of the gcncircular
    published_time = parse(gcn_circular.header['date'], parserinfo=parserinfo(yearfirst=True))

    message, created = Message.objects.get_or_create(
        # fields to be compared to find existing Message (if any)
        topic=metadata.topic,
        uuid=get_or_create_uuid_from_metadata(metadata),
        message_text=gcn_circular.body,
        published=published_time,
        title=gcn_circular.header['subject'],
        submitter='Hop gcn.circular',
        authors=gcn_circular.header['from'],
        data=gcn_circular.header
    )
    GCN_CIRCULAR_PARSER.parse(message)

    if created:
        logger.debug(f'created new Message with id: {message.id} and uuid: {message.uuid}')
    else:
        logger.debug(f'found existing Message with and uuid: {message.uuid} id: {message.id}')


def handle_igwn_message(message: JSONBlob, metadata: Metadata):
    alert = message.content[0]
    # Only store test alerts if we are configured to do so
    if alert.get('superevent_id', '').startswith('M') and not settings.SAVE_TEST_MESSAGES:
        return
    # These alerts have a created timestamp, so use that for the published time instead of metadata timestamp
    published_time: datetime.date = parse(alert.get('time_created'))
    # Generate a descriptive title for these: event id + alert type
    title = f"{alert.get('superevent_id')} - {alert.get('alert_type')}"
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
            alert['urls']['skymap'] = f"https://gracedb.ligo.org/api/superevents/{alert['superevent_id']}/files/bayestar.multiorder.fits,{skymap_version}"
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
            alert['urls']['combined_skymap'] = f"https://gracedb.ligo.org/api/superevents/{alert['superevent_id']}/files/combined-ext.multiorder.fits,{combined_skymap_version}"
    alert['sequence_num'] = get_sequence_number(alert['superevent_id'])

    logger.debug(f"Storing message for igwn alert {alert_uuid}: {alert}")
    try:
        message, created = Message.objects.update_or_create(
            # all these fields must match for update...
            topic=metadata.topic,
            uuid=alert_uuid,
            title=title,
            submitter=get_sender_from_metadata(metadata),
            authors='LVK',
            data=alert,
            message_text='',
            published=published_time,
        )
    except KeyError as err:
        logger.error(f'Required key not found in {metadata.topic} alert: {alert_uuid}.')
        return

    IGWN_ALERT_PARSER.parse(message)

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
    if hermes_message.content['topic'] in ['hermes.test', 'tomtoolkit.test'] and not settings.SAVE_TEST_MESSAGES:
        return

    # metadata.timestamp is the number of milliseconds since the epoch (UTC).
    published_time: datetime.date = datetime.fromtimestamp(metadata.timestamp/1e3, tz=timezone.utc)

    try:
        message, created = Message.objects.update_or_create(
            # all these fields must match for update...
            topic=hermes_message.content['topic'],
            uuid=get_or_create_uuid_from_metadata(metadata),
            title=hermes_message.content['title'],
            submitter=hermes_message.content['submitter'],
            authors=hermes_message.content['authors'],
            data=hermes_message.content['data'],
            message_text=hermes_message.content['message_text'],
            published=published_time,
        )
    except KeyError as err:
        logger.error(f'Required key not found in {metadata.topic} alert: {hermes_message}.')
        return
    
    HERMES_PARSER.parse(message)

    if created:
        logger.debug(f'created new Message with id: {message.id} and uuid: {message.uuid}')
    else:
        logger.debug(f'found existing Message with and uuid: {message.uuid} id: {message.id}')

