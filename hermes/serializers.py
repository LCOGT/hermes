from hermes.models import Message
from rest_framework import serializers


class MessageSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Message
        fields = ['url', 'id', 'title', 'author', 'timestamp', 'data', 'message_text']
