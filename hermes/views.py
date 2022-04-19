import json
import logging
import os

from django.views.generic import ListView, DetailView, FormView, RedirectView
from django.urls import reverse_lazy
from django.shortcuts import redirect

from hop import Stream
from hop.auth import Auth

from rest_framework import viewsets

from hermes.models import Message
from hermes.forms import MessageForm
from hermes.serializers import MessageSerializer

logger = logging.getLogger(__name__)

class MessageViewSet(viewsets.ModelViewSet):
    queryset = Message.objects.all()
    serializer_class = MessageSerializer
    pagination_class = None


class MessageListView(ListView):
    model = Message


class MessageDetailView(DetailView):
    model = Message


class MessageFormView(FormView):
    template_name = "hermes/generic_message.html"
    form_class = MessageForm
    success_url = reverse_lazy('index')

    def form_valid(self, form):
        super().form_valid(form)
        new_message_data = form.cleaned_data

        # List of universal Fields
        non_json_fields = ['title', 'author', 'message_text']
        non_json_dict = {key: new_message_data[key] for key in new_message_data.keys() if key in non_json_fields}
        message = Message(**non_json_dict)

        # convert form specific data to JSON
        json_dict = {key: new_message_data[key] for key in new_message_data.keys() if key not in non_json_fields}
        json_data = json.dumps(json_dict, indent=4)
        message.data = json_data

        message.save()

        return redirect(self.get_success_url())


class HopSubmitView(RedirectView):
    """Intercept the re-direct and submit the message to the hop-client.
    """
    # redirect to the this URL after submitting the message
    url = '/messages'

    def get(self, request, *args, **kwargs):
        # what's going on here?
        logger.info(f'args: {args}')
        logger.info(f'kwargs: {kwargs}')
        logger.info(f'dir(request): {dir(request)}')
        logger.info(f'request: {request}')
        logger.info(f'request.GET: {dir(request.GET)}')
        logger.info(f'type(request.body): {type(request.body)}')
        logger.info(f'request.body: {request.body}')

        # extract the message JSON from the HTTPRequest
        try:
            message = json.loads(request.body.decode("utf-8"))
            logger.info(f'message: {message}')
        except json.JSONDecodeError as err:
            logger.error(f'JSONDecodeError: {err} for request body: {request.body}')

        # TODO: submit the message to scimma hopskotch via hop-client
        # handle authenticaion: HOP_USERNAME and HOP_PASSWORD should enter
        #   the environment as k8s secrets
        username = os.getenv('HOP_USERNAME', None)
        password = os.getenv('HOP_PASSWORD', None)
        if username is None or password is None:
            error_message = 'Supply Hop credentials: set HOP_USERNAME and HOP_PASSWORD environment variables.'
            logger.error(error_message)
        hop_auth = Auth(username, password)

        topic = 'hermes.test'
        stream = Stream(auth=hop_auth)
        # open for write ('w')
        with stream.open(f'kafka://kafka.scimma.org/{topic}', 'w') as s:
            metadata = {'topic': topic}
            s.write(message, metadata)

        # and now let the RedirectView handle the redirect
        return super().get(request, args, kwargs)


    # these post and patch overrides mirror the RedirectView base class behavior
    def post(self, request, *args, **kwargs):
        return self.get(request, args, kwargs)
    def patch(self, request, *args, **kwargs):
        return self.get(request, args, kwargs)
