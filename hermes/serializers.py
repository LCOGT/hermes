from hermes.models import Message
from rest_framework import serializers


class MessageSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Message
        fields = [
            'url',
            'id',
            'topic',
            'title',
            'author',
            'data',
            'message_text',
            'published'
            'created',
            'modified'
        ]
