''' This class defines a message handler for a tom_alertstreams connection to GCN over kafka
    text formatted streams.
'''
import logging
import uuid

from hermes.models import Message
from hermes import parsers

logger = logging.getLogger(__name__)


TOPICS_TO_PARSERS = {
    'gcn.classic.text.LVC_COUNTERPART': parsers.GCNLVCCounterpartNoticeParser(),
    'gcn.classic.text.LVC_INITIAL': parsers.GCNLVCNoticeParser(),
    'gcn.classic.text.LVC_PRELIMINARY': parsers.GCNLVCNoticeParser(),
    'gcn.classic.text.LVC_RETRACTION': parsers.GCNLVCNoticeParser(),
    'gcn.classic.text.LVC_UPDATE': parsers.GCNLVCNoticeParser(),
    'gcn.classic.text.LVC_EARLY_WARNING': parsers.GCNLVCNoticeParser(),
}

def handle_message(message):
    # It receives a Kafka Cimpl.message
    topic = message.topic()
    message_text = message.value().decode('utf-8')

    message, created = Message.objects.get_or_create(
        topic=topic,
        message_text=message_text,
        defaults={
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
