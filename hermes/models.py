from django.db import models
from rest_framework.reverse import reverse


class Message(models.Model):
    title = models.CharField(max_length=50, blank=True)
    author = models.CharField(max_length=50, blank=True)
    data = models.JSONField(null=True)
    message_text = models.TextField(blank=True)

    def __str__(self):
        return self.title
