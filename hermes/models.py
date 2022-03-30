from django.db import models


class Message(models.Model):
    title = models.CharField(max_length=50, blank=True)
    author = models.CharField(max_length=50, blank=True)
    data = models.JSONField()
    message_text = models.TextField()
