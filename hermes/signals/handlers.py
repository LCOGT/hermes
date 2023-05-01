
from django.dispatch import receiver
from django.db.models.signals import post_save
from django.core.cache import cache

from hermes.models import Message

import logging
logger = logging.getLogger(__name__)


@receiver(post_save, sender=Message)
def cb_post_save_message(sender, instance, created, **kwargs):
    # Anytime a message is saved, check if its topic is in the cache and if not add it to the cache
    if created:
        topic = instance.topic
        all_topics = cache.get("all_public_topics", None)
        if all_topics and topic not in all_topics:
            all_topics.push(topic)
            cache.set("all_public_topics", all_topics, 3600)
