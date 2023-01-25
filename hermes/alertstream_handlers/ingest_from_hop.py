''' This class defines a message handler for a tom_alertstreams connection to hop streams.
'''
from datetime import datetime, timezone
from dateutil.parser import parse, parserinfo
import logging
import uuid

from hop.io import Metadata
from hop.models import GCNCircular, JSONBlob

from hermes.models import Message
from hermes import parsers

logger = logging.getLogger(__name__)

GCN_CIRCULAR_PARSER = parsers.GCNCircularParser()
HERMES_PARSER = parsers.HermesMessageParser()

TOPIC_PIECES_TO_IGNORE = [
    'gcn.notice',
    'heartbeat'
]

def should_ingest_topic(topic):
    for topic_piece in TOPIC_PIECES_TO_IGNORE:
        if topic_piece in topic.lower():
            return False
    return True


def get_or_create_uuid_for_message(metadata: Metadata) -> uuid.UUID:
    """Extract the UUID from the message metadata, or generate a UUID if none present in metadata.

    The headers property of the metadata is a list of tuples of the form [('key', value), ...].
    """
    # get the tuple with the uuid: key is '_id'
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
            uuid=get_or_create_uuid_for_message(metadata),
            published=published_time,
            data=message.content,
            defaults={
                'message_text': str(metadata._raw.value())
            }
        )
        if created:
            logger.debug(f'created new Message with id: {message.id}')
        else:
            logger.debug(f'found existing Message with id: {message.id}')

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
        uuid=get_or_create_uuid_for_message(metadata),
        message_text=gcn_circular.body,
        published=published_time,
        title=gcn_circular.header['subject'],
        submitter='Hop gcn.circular',
        authors=gcn_circular.header['from'],
        data=gcn_circular.header
    )
    GCN_CIRCULAR_PARSER.parse(message)

    if created:
        logger.debug(f'created new Message with id: {message.id}')
    else:
        logger.debug(f'found existing Message with id: {message.id}')

def handle_hermes_message(hermes_message: JSONBlob,  metadata: Metadata):
    """Ingest a Hermes-published alert.

    This method understands that Hermes-published alerts have the following content keys:
    'topic', 'title', 'authors', 'data', and 'message_text'.
    """
    logger.debug(f'updating db with hermes alert {hermes_message}')
    logger.debug(f'metadata: {metadata}')

    # metadata.timestamp is the number of milliseconds since the epoch (UTC).
    published_time: datetime.date = datetime.fromtimestamp(metadata.timestamp/1e3, tz=timezone.utc)

    try:
        message, created = Message.objects.update_or_create(
            # all these fields must match for update...
            topic=hermes_message.content['topic'],
            uuid=get_or_create_uuid_for_message(metadata),
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
        logger.info(f'created new Message with id: {message.id}')
    else:
        logger.info(f'found existing Message with id: {message.id}')

