from django.shortcuts import render
from hermes.models import Message
from rest_framework import viewsets
from hermes.serializers import MessageSerializer


class MessageViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows Telescopes to be viewed or edited.
    """
    queryset = Message.objects.all()
    serializer_class = MessageSerializer
