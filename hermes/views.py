from hermes.models import Message
from rest_framework import viewsets
from hermes.serializers import MessageSerializer
from django.views.generic import ListView, DetailView


class MessageViewSet(viewsets.ModelViewSet):
    queryset = Message.objects.all()
    serializer_class = MessageSerializer


class MessageListView(ListView):
    model = Message


class MessageDetailView(DetailView):
    model = Message
