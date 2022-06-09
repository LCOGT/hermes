import json
import logging
import os

# this is for OIDC experimentation
from django.contrib.auth.models import User

from django.views.decorators.csrf import csrf_exempt
from django.views.generic import ListView, DetailView, FormView
from django.urls import reverse_lazy
from django.shortcuts import redirect
from rest_framework.views import APIView
from rest_framework import status
from rest_framework.response import Response

from astropy.coordinates import SkyCoord
from astropy import units

from marshmallow import Schema, fields, ValidationError, validates_schema

from hop import Stream
from hop.auth import Auth

from rest_framework import viewsets

from hermes.models import Message
from hermes.forms import MessageForm
from hermes.serializers import MessageSerializer

logger = logging.getLogger(__name__)


class CandidateDataSchema(Schema):
    candidate_id = fields.String(required=True)
    ra = fields.String(required=True)
    dec = fields.String(required=True)
    discovery_date = fields.String(required=True)
    telescope = fields.String()
    instrument = fields.String()
    band = fields.String(required=True)
    brightness = fields.Float()
    brightnessError = fields.Float()
    brightnessUnit = fields.String()

    @validates_schema(skip_on_field_errors=True)
    def validate_coordinates(self, data):
        for row in data:
            try:
                ra, dec = float(row['ra']), float(row['dec'])
                SkyCoord(ra, dec, unit=(units.deg, units.deg))
            except:
                try:
                    SkyCoord(row['ra'], row['dec'], unit=(units.hourangle, units.deg))
                except:
                    raise ValidationError('Coordinates do not all have valid RA and Dec')

    @validates_schema(skip_on_field_errors=True)
    def validate_brightness_unit(self, data):
        brightness_units = ['AB mag', 'Vega mag']
        for row in data:
            if row['brightness_unit'] not in brightness_units:
                raise ValidationError(f'Unrecognized brightness unit. Accepted brightness units are {brightness_units}')


class CandidateMessageSubSchema(Schema):
    authors = fields.String()
    main_data = fields.Nested(CandidateDataSchema)


class CandidateMessageSchema(Schema):
    title = fields.String(required=True)
    topic = fields.String(required=True)
    event_id = fields.String()
    message_text = fields.String(required=True)
    author = fields.String(required=True)
    data = fields.Nested(CandidateMessageSubSchema)


class MessageViewSet(viewsets.ModelViewSet):
    queryset = Message.objects.all()
    serializer_class = MessageSerializer
    pagination_class = None


class MessageListView(ListView):
    # change the model form Message to User for OIDC experimentation
    model = User
    template_name = 'hermes/message_list.html'


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


def submit_to_hop(message):
    # TODO: submit the message to scimma hopskotch via hop-client
    # handle authentication: HOP_USERNAME and HOP_PASSWORD should enter
    # the environment as k8s secrets
    username = os.getenv('HOP_USERNAME', None)
    password = os.getenv('HOP_PASSWORD', None)
    if username is None or password is None:
        error_message = 'Supply Hop credentials: set HOP_USERNAME and HOP_PASSWORD environment variables.'
        logger.error(error_message)
        return Response({'message': 'Hop credentials are not set correctly on the server'},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    hop_auth = Auth(username, password)

    try:
        topic = 'hermes.test'
        stream = Stream(auth=hop_auth)
        # open for write ('w')
        with stream.open(f'kafka://kafka.scimma.org/{topic}', 'w') as s:
            metadata = {'topic': topic}
            s.write(message, metadata)
    except Exception as e:
        return Response({'message': f'Error posting message to kafka: {e}'},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    return Response({"message": {"Message was submitted successfully"}}, status=status.HTTP_200_OK)


class HopSubmitView(APIView):
    """
    Submit a message to the hop client
    """
    @csrf_exempt
    def post(self, request, *args, **kwargs):
        # what's going on here?
        logger.info(f'args: {args}')
        logger.info(f'kwargs: {kwargs}')
        logger.info(f'dir(request): {dir(request)}')
        logger.info(f'request: {request}')
        logger.info(f'request.POST: {dir(request.POST)}')
        # request.data does not read the data stream again. So,
        # that is more appropriate than request.body which does
        # (read the stream again).
        # NO:
        #logger.info(f'type(request.body): {type(request.body)}')
        #logger.info(f'request.body: {request.body}')
        # YES:
        logger.info(f'type(request.data): {type(request.data)}')
        logger.info(f'request.data: {request.data}')
        return submit_to_hop(request.data)

    def get(self, request, *args, **kwargs):
        return Response({"message": "Supply any valid json to send a message to kafka."}, status=status.HTTP_200_OK)


class HopSubmitCandidatesView(APIView):
    def get(self, request, *args, **kwargs):
        message = """This endpoint is used to send a message with a list of potential candidates corresponding to a 
        non-localized event.
        
        Requests should be structured as below:
        
        {title: <Title of the message>,
         topic: <kafka topic to post message to>, 
         author: <submitter of the message>,
         message_text: <Text of the message to send>,
         event_id: <ID of the non-localized event for these candidates>,
         data: {authors: <Text full list of authors on a message>,
                main_data: {[{candidate_id: <ID of the candidate>,
                              ra: <Right Ascension in hh:mm:ss.ssss or decimal degrees>,
                              dec: <Declination in dd:mm:ss.ssss or decimal degrees>,
                              discovery_date: <Date/time of the candidate discovery>,
                              telescope: <Discovery telescope>,
                              instrument: <Discovery instrument>,
                              band: <Wavelength band of the discovery observation>,
                              brightness: <Brightness of the candidate at discovery>,
                              brightness_error: <Brightness error of the candidate at discovery>,
                              brightness_unit: <Brightness units for the discovery, 
                                  current supported values: [AB mag, Vega mag]>
                           }, ...]}
        }
        """
        return Response({"message": message}, status.HTTP_200_OK)

    def post(self, request, *args, **kwargs):
        candidate_schema = CandidateMessageSchema()
        candidates, errors = candidate_schema.load(request.json)

        logger.debug(f"Request data: {request.json}")
        if errors:
            return Response(errors, status.HTTP_400_BAD_REQUEST)

        return submit_to_hop(vars(candidates))
