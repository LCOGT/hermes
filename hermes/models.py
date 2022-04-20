from pydoc_data.topics import topics
from django.db import models


class Message(models.Model):
    topic = models.CharField(max_length=256, blank=True)
    title = models.CharField(max_length=256, blank=True)
    author = models.CharField(max_length=1024, blank=True)
    data = models.JSONField(null=True)
    message_text = models.TextField(blank=True, max_length=2048)

    created = models.DateTimeField(auto_now_add=True, verbose_name='Time Created')
    modified = models.DateTimeField(auto_now=True, verbose_name='Last Modified')

    def __str__(self):
        return f'{self.topic}: {self.title} from {self.author}'
