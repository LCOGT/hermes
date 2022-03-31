from django.db import models
from rest_framework.reverse import reverse


class Message(models.Model):
    title = models.CharField(max_length=50, blank=True)
    author = models.CharField(max_length=50, blank=True)
    data = models.JSONField()
    message_text = models.TextField()

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('message-info', kwargs={'pk': self.pk})
