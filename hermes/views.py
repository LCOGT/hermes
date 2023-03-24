from http.client import responses
import json
import logging

from django.contrib.auth.models import User
from django.conf import settings

#from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.middleware import csrf

from django.views.generic import ListView, DetailView, FormView, RedirectView, View
from django.urls import reverse_lazy
from django.shortcuts import redirect
from rest_framework.decorators import action
from rest_framework import status, viewsets, filters
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.generics import RetrieveUpdateAPIView
from django_filters.rest_framework import DjangoFilterBackend

from hop import Stream
from hop.auth import Auth

from hermes.brokers import hopskotch
from hermes.models import Message, Target, NonLocalizedEvent, NonLocalizedEventSequence
from hermes.forms import MessageForm
from hermes.utils import get_all_public_topics, extract_hop_auth
from hermes.filters import MessageFilter, TargetFilter, NonLocalizedEventFilter, NonLocalizedEventSequenceFilter
from hermes.serializers import (MessageSerializer, TargetSerializer, NonLocalizedEventSerializer, HermesMessageSerializer,
                                NonLocalizedEventSequenceSerializer, ProfileSerializer)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class MessageViewSet(viewsets.ModelViewSet):
    queryset = Message.objects.all()
    http_method_names = ['get', 'head', 'options']
    serializer_class = MessageSerializer
    filterset_class = MessageFilter
    filter_backends = (
        filters.OrderingFilter,
        DjangoFilterBackend
    )
    ordering = ('-id',)

    def retrieve(self, request, pk=None):
        try:
            instance = Message.objects.get(uuid__startswith=pk)
        except:
            instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response(serializer.data)


class TargetViewSet(viewsets.ModelViewSet):
    queryset = Target.objects.all()
    http_method_names = ['get', 'head', 'options']
    serializer_class = TargetSerializer
    filterset_class = TargetFilter
    filter_backends = (
        filters.OrderingFilter,
        DjangoFilterBackend
    )
    ordering = ('-id',)


class NonLocalizedEventViewSet(viewsets.ModelViewSet):
    queryset = NonLocalizedEvent.objects.all()
    http_method_names = ['get', 'head', 'options']
    serializer_class = NonLocalizedEventSerializer
    filterset_class = NonLocalizedEventFilter
    filter_backends = (
        DjangoFilterBackend,
    )

    @action(detail=True, methods=['get'])
    def targets(self, request, pk=None):
        targets = Target.objects.filter(messages__nonlocalizedevents__event_id=pk)
        return Response(TargetSerializer(targets, many=True).data)

    @action(detail=True, methods=['get'])
    def sequences(self, request, pk=None):
        sequences = NonLocalizedEventSequence.objects.filter(event__event_id=pk)
        return Response(NonLocalizedEventSequenceSerializer(sequences, many=True).data)


class NonLocalizedEventSequenceViewSet(viewsets.ModelViewSet):
    queryset = NonLocalizedEventSequence.objects.all()
    http_method_names = ['get', 'head', 'options']
    serializer_class = NonLocalizedEventSequenceSerializer
    filterset_class = NonLocalizedEventSequenceFilter
    filter_backends = (
        filters.OrderingFilter,
        DjangoFilterBackend
    )
    ordering = ('-id',)


class TopicViewSet(viewsets.ViewSet):
    """This ViewSet does not have a Model backing it. It returns the cached list of (public) topics ingested in hermes.
    """
    def list(self, request, *args, **kwargs) -> JsonResponse:
        all_topics = get_all_public_topics()
        response = JsonResponse(data={'topics': all_topics})
        return response


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
        non_json_fields = ['title', 'authors', 'message_text']
        non_json_dict = {key: new_message_data[key] for key in new_message_data.keys() if key in non_json_fields}
        message = Message(**non_json_dict)

        # convert form specific data to JSON
        json_dict = {key: new_message_data[key] for key in new_message_data.keys() if key not in non_json_fields}
        json_data = json.dumps(json_dict, indent=4)
        message.data = json_data

        message.save()

        return redirect(self.get_success_url())


def submit_to_hop(request, message):
    """Open the Hopskotch kafka stream for write and publish an Alert

    The request holds the Session dict which has the 'hop_user_auth_json` key
    whose value can be deserialized into a hop.auth.Auth instance to open the
    stream with. (The hop.auth.Auth instance was added to the Session dict upon
    logon via the HopskotchOIDCAuthenticationBackend.authenticate method).
    """
    try:
        hop_auth: Auth = extract_hop_auth(request)
    except KeyError as err:
        logger.error(f'Hopskotch Authorization for User {request.user.username} not found.  err: {err}')
        # TODO: REMOVE THE FOLLOWING CODE AFTER TESTING!!
        # use the Hermes service account temporarily while testing...
        logger.warning(f'Submitting with Hermes service account authorization (testing only)')
        hop_auth: Auth = hopskotch.get_hermes_hop_authorization()

    logger.info(f'submit_to_hop User {request.user} with credentials {hop_auth.username}')

    logger.debug(f'submit_to_hop request: {request}')
    logger.debug(f'submit_to_hop request.data: {request.data}')
    logger.debug(f'submit_to_hop s.write => message: {message}')

    try:
        topic = request.data['topic']
        stream = Stream(auth=hop_auth)
        # open for write ('w') returns a hop.io.Producer instance
        with stream.open(f'kafka://kafka.scimma.org/{topic}', 'w') as producer:
            metadata = {'topic': topic}
            producer.write(message, metadata)
    except Exception as e:
        return Response({'message': f'Error posting message to kafka: {e}'},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    return Response({"message": "Message was submitted successfully."}, status=status.HTTP_200_OK)


class SubmitHermesMessageViewSet(viewsets.ViewSet):
    serializer_class = HermesMessageSerializer
    
    def get(self, request, *args, **kwargs):
        message = """This endpoint is used to send a generic hermes message
        
        Requests should be structured as below:
        
        {title: <Title of the message>,
         topic: <kafka topic to post message to>, 
         submitter: <submitter of the message>,
         authors: <Full list of authors on a message>,
         message_text: <Text of the message to send>,
         submit_to_tns: <Boolean of whether or not to submit this message to TNS along with hop>
         submit_to_mpc: <Boolean of whether or not to submit this message to MPC along with hop>
         data: {
            references: [
                {
                    source:
                    citation:
                    url:
                },
                ...
            ],
            extra_data: {
                key1: value1,
                key2: value2,
                ...
            },
            event_id: <Nonlocalized event_id this message relates to>,
            targets: [
                {
                    name: <Target name>,
                    ra: <Target ra in decimal or sexigesimal format>,
                    dec: <Target dec in decimal or sexigesimal format>,
                    ra_error: <Error of ra>,
                    dec_error: <Error of dec>,
                    ra_error_units: <Units for ra_error>,
                    dec_error_units: <Units for dec_error>,
                    pm_ra: <RA proper motion in arcsec/year>,
                    pm_dec: <Dec proper motion in arcsec/year>,
                    epoch: <Epoch of reference frame>,
                    new_discovery: <Boolean if this target is for a new discovery or not>
                    orbital_elements: {
                        epoch_of_elements: <Epoch of Elements in MJD>,
                        orbital_inclination: <Orbital Inclination (i) in Degrees>,
                        longitude_of_the_ascending_node: <Longitude of the Ascending Node (Ω) in Degrees>,
                        argument_of_the_perihelion: <Argument of Periapsis (ω) in Degrees>,
                        eccentricity: <Orbital Eccentricity (e)>,
                        semimajor_axis: <Semimajor Axis (a) in AU>,
                        mean_anomaly: <Mean Anomaly (M) in Degrees>,
                        perihperihelion_distancedist: <Distance to the Perihelion (q) in AU>,
                        epoch_of_perihelion: <Epoch of Perihelion passage (tp) in MJD>
                    },
                    discovery_info: {
                        reporting_group: <>,
                        discovery_source: <>,
                        transient_type: <Type of source, one of PSN, nuc, PNV, AGN, or Other>,
                        proprietary_period: <Duration that this discovery should be kept private>,
                        proprietary_period_units: <Units for proprietary period, Days, seconds, Years>
                    },
                    redshift: <>,
                    host_name: <Host galaxy name>,
                    host_redshift: <Redshift (z) of Host Galaxy>,
                    aliases: [
                        'alias1',
                        'alias2',
                        ...
                    ],
                    group_associations: <String of group associations for this target>
                }
            ],
            photometry: [
                {
                    target_index: <Index of target list that this photometry relates to. Can be left out if there is only one target>,
                    date_obs: <Date of the observation, in a parseable format or JD>,
                    telescope: <Observation telescope>,
                    instrument: <Observation instrument>,
                    bandpass: <Wavelength band of the observation>,
                    brightness: <Brightness of the observation>,
                    brightness_error: <Brightness error of the observation>,
                    brightness_unit: <Brightness units for the observation,
                                      current supported values: [AB mag, Vega mag, mJy, erg / s / cm² / Å]>,
                    exposure_time: <Exposure time in seconds for this photometry>,
                    observer: <The entity that observed this photometry data>,
                    comments: <String of comments for the photometry>,
                    limiting_brightness: <The minimum brightness at which the target is visible>,
                    limiting_brightness_unit: <Unit for the limiting brightness>
                    catalog: <Photometric catalog used to reduce this data>,
                    group_associations: <>
                }
            ],
            spectroscopy: [
                {
                    target_index: <Index of target list that this specotroscopic datum relates to. Can be left out if there is only one target>,
                    date_obs: <Date of the observation, in a parseable format or JD>,
                    telescope: <specotroscopic datum telescope>,
                    instrument: <specotroscopic datum instrument>,
                    setup: <>,
                    flux: [<Flux values of the specotroscopic datum>],
                    flux_error: [ <Flux error values of the specotroscopic datum>],
                    flux_units: <Flux units for the specotroscopic datum,
                               current supported values: [AB mag, Vega mag, mJy, erg / s / cm² / Å]>
                    wavelength: [<Wavelength values for this spectroscopic datum>],
                    wavelength_units: <Units for the wavelength>,
                    classification: <TNS classification for this specotroscopic datum>,
                    proprietary_period: <>,
                    proprietary_period_units: <>,
                    exposure_time: <Exposure time in seconds for this spectroscopic datum>,
                    observer: <The entity that observed this spectroscopic datum>,
                    reducer: <The entity that reduced this spectroscopic datum>,
                    comments: <String of comments for the spectroscopic datum>,
                    group_associations: <>,
                    spec_type: <>
                }
            ],
            astrometry: [
                {
                    date_obs: <Date of the observation, in a parseable format or JD>,
                    telescope: <Astrometry telescope>,
                    instrument: <Astrometry instrument>,
                    ra: <Target ra in decimal or sexigesimal format>,
                    dec: <Target dec in decimal or sexigesimal format>,
                    ra_error: <Error of ra>,
                    dec_error: <Error of dec>,
                    ra_error_units: <Units for ra error>,
                    dec_error_units: <Units for dec error>,
                    mpc_sitecode: <MPC Site code for this data>,
                    catalog: <Astrometric catalog used to reduce this data>,
                    comments: <String of comments for the astrometric datum>
                }
            ],
         }
        }
        """
        return Response({"message": message}, status.HTTP_200_OK)

    def create(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data, context={'request': request})
        if serializer.is_valid():
            data = serializer.validated_data
            return submit_to_hop(request, data)
        else:
            return Response(serializer.errors, status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'])
    def validate(self, request):
        """ Validate a Message Schema
        """
        serializer = self.serializer_class(data=request.data, context={'request': request})
        if serializer.is_valid():
            errors = {}
        else:
            errors = serializer.errors
        return Response(errors, status.HTTP_200_OK)


class ProfileApiView(RetrieveUpdateAPIView):
    serializer_class = ProfileSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        logger.warning(f"user pk = {self.request.user.pk}, user = {self.request.user}")
        """Once authenticated, retrieve profile data"""
        qs = User.objects.filter(pk=self.request.user.pk).prefetch_related(
            'profile'
        )
        return qs.first().profile


class LoginRedirectView(RedirectView):
    pattern_name = 'login-redirect'

    def get(self, request, *args, **kwargs):

        logger.debug(f'LoginRedirectView.get -- request.user: {request.user}')

        login_redirect_url = f'{settings.HERMES_FRONT_END_BASE_URL}'
        logger.info(f'LoginRedirectView.get -- setting self.url and redirecting to {login_redirect_url}')
        self.url = login_redirect_url

        return super().get(request, *args, **kwargs)

class LogoutRedirectView(RedirectView):
    pattern_name = 'logout-redirect'

    def get(self, request, *args, **kwargs):

        logout_redirect_url = f'{settings.HERMES_FRONT_END_BASE_URL}'
        logger.info(f'LogoutRedirectView.get setting self.url and redirecting to {logout_redirect_url}')
        self.url = logout_redirect_url

        return super().get(request, *args, **kwargs)


class GetCSRFTokenView(View):
    pattern_name = 'get-csrf-token'

    def get(self, request, *args, **kwargs) -> JsonResponse:
        """return a CSRF token from the middleware in a JsonResponse:
        key: 'token'
        value: <csrf token>

        The frontend can call this method upon start-up, store the token
        in a cookie, and include it in subsequent calls like this:
        headers: {'X-CSRFToken': this_token}
        """
        token = csrf.get_token(request)
        response = JsonResponse(data={'token': token})
        # this is where you can modify or log the response before returning it
        return response
