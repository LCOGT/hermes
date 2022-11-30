from pydoc_data.topics import topics
from django.db import models


class Message(models.Model):
    class Meta:
        # -created means newest first
        ordering = ['-created']  # to avoid DRF pagination UnorderedObjectListWarning

    topic = models.TextField(blank=True)
    title = models.TextField(blank=True)
    author = models.TextField(blank=True)
    data = models.JSONField(null=True)
    message_text = models.TextField(blank=True)

    published = models.DateTimeField(null=True,
                                     verbose_name='Time Published to Stream from message metadata.')

    created = models.DateTimeField(auto_now_add=True, verbose_name='Time Created')
    modified = models.DateTimeField(auto_now=True, verbose_name='Last Modified')

    def __str__(self):
        return f'{self.topic}: {self.title} from {self.author}'
