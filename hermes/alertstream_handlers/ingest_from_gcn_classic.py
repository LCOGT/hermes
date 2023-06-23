''' This class defines a message handler for a tom_alertstreams connection to GCN over kafka
    text formatted streams.
'''
import logging
import uuid

from hermes.models import Message
from hermes import parsers

logger = logging.getLogger(__name__)


GENERIC_NOTICE_PARSER = parsers.GCNNoticePlaintextParser()
TOPICS_TO_PARSERS = {}

def handle_message(message):
    # It receives a Kafka Cimpl.message
    topic = message.topic()
    message_text = message.value().decode('utf-8')

    # GCNClassicOverKafka does not yet provide message UUIDs (so get one now)
    message_uuid: uuid.UUID = uuid.uuid4()

    message, created = Message.objects.get_or_create(
        topic=topic,
        message_text=message_text,
        defaults={
            'uuid': message_uuid,
            'submitter':'GCN Classic Over Kafka',
        }
    )

    if created:
        logger.info(f"Ingested new Message {message.id} on topic {message.topic}")
    else:
        logger.info(f"Ignoring duplicate Message {message.id} on topic {message.topic}")

    if topic in TOPICS_TO_PARSERS:
        parser = TOPICS_TO_PARSERS[topic]
        parser.parse(message)
    else:
        GENERIC_NOTICE_PARSER.parse(message)
