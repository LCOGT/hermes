from http.client import responses
import json
import logging
import uuid
from urllib.parse import urljoin
import requests

from django.contrib.auth.models import User
from django.conf import settings
from django.contrib import messages
from django.http import HttpResponse

#from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.middleware import csrf
from django.core.cache import cache
from django.views.generic import ListView, DetailView, FormView, RedirectView, View
from django.urls import reverse_lazy
from django.shortcuts import redirect
from django.http import Http404
from rest_framework.decorators import action
from rest_framework.exceptions import APIException
from rest_framework import status, viewsets, filters
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.generics import RetrieveAPIView
from rest_framework.authtoken.models import Token
from django_filters.rest_framework import DjangoFilterBackend

from hop import Stream
from hop.auth import Auth

from hermes.brokers import hopskotch
from hermes.models import Message, Target, NonLocalizedEvent, NonLocalizedEventSequence, OAuthToken
from hermes.forms import MessageForm
from hermes.tns import get_tns_values, convert_hermes_message_to_tns, submit_at_report_to_tns, submit_files_to_tns, BadTnsRequest
from hermes.utils import get_all_public_topics, convert_to_plaintext, send_email, MultipartJsonFileParser
from hermes.filters import MessageFilter, TargetFilter, NonLocalizedEventFilter, NonLocalizedEventSequenceFilter
from hermes.serializers import (MessageSerializer, TargetSerializer, NonLocalizedEventSerializer, HermesMessageSerializer,
                                NonLocalizedEventSequenceSerializer, ProfileSerializer)
from hermes.oauth_clients import oauth, update_token, get_access_token

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
            raise Http404
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @action(detail=True)
    def plaintext(self, request, pk=None):
        try:
            instance = Message.objects.get(uuid__startswith=pk)
        except:
            raise Http404
        serializer = self.get_serializer(instance)
        plaintext_message = convert_to_plaintext(serializer.data)

        return Response(plaintext_message)


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
    if request.user.is_authenticated and request.user.profile.credential_name and request.user.profile.credential_password:
        hop_auth = Auth(user=request.user.profile.credential_name, password=request.user.profile.credential_password)
    else:
        logger.error(f'Hopskotch Authorization for User {request.user.username} not found.')
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
            payload, headers = producer.pack(message, metadata)
            message_uuid_tuple = next((item for item in headers if item[0] == '_id'), None)
            message_uuid = None
            if message_uuid_tuple:
                message_uuid = uuid.UUID(bytes=message_uuid_tuple[1])
            producer.write_raw(payload, headers)
    except Exception as e:
        raise APIException(f'Error posting message to kafka: {e}')

    return message_uuid


def submit_to_gcn(request, message, message_uuid):
    # TODO: Add code to submit the message with its message_uuid to gcn here.
    # First add the uuid into the message, then transfer the message into plaintext format
    message_plaintext = convert_to_plaintext(message)
    message_plaintext += '\n\n This message was sent via HERMES.  A machine readable version can be found at ' \
                         + urljoin(settings.HERMES_FRONT_END_BASE_URL, f'messages/{str(message_uuid)}')
    # Then submit the plaintext message to gcn via email
    message_data = {'subject': message['title'], 'body': message_plaintext}
    access_token = get_access_token(request.user, OAuthToken.IntegratedApps.GCN)

    headers =  {'Authorization': f'Bearer {access_token}'}
    try:
        response = requests.post(settings.GCN_SUBMISSION_URL, headers=headers, json=message_data)
        logger.warning(f"Submitted to GCN response: {response.content}")
        response.raise_for_status()
        logger.warning(f"GCN submission successful: {response.json()}")
    except Exception as e:
        logger.warning(f"Failed to submit to GCN: {repr(e)}")
        return Response({"message":  f"Submitted message with uuid {message_uuid} to Hop, GCN submission failed."},
                        status=status.HTTP_200_OK)

    return Response({"message":  f"Submitted message with uuid {message_uuid} to Hop and GCN"},
                    status=status.HTTP_200_OK)


class SubmitHermesMessageViewSet(viewsets.ViewSet):
    EXPECTED_DATA_KEYS = ['targets', 'event_id', 'references', 'photometry', 'spectroscopy', 'astrometry']
    serializer_class = HermesMessageSerializer
    parser_classes = (MultipartJsonFileParser, JSONParser)

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
         submit_to_gcn: <Boolean of whether or not to submit this message to GCN along with hop>
         data: {
            references: [
                {
                    source:
                    citation:
                    url:
                },
                ...
            ],
            extra_key1: value1,
            extra_key2: value2,
                ...
            extra_keyn: <Any key within data not used by the hermes message format will be passed through in the message>
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
                    group_associations: [
                        'group one',
                        'group two',
                        ...
                    ]
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
        # This method can now handle either json encoded data, or multipart/form-data with json and files.
        data = request.data
        if 'multipart/form-data' in request.content_type:
            files = request.data.getlist('files')  # Need to explicitly pull out the files since they don't translate well in .dict()
            data = data.dict()
            if 'files' in data:
                data['files'] = files
        non_serialized_data = {key: val for key, val in data.get('data', {}).items() if key not in self.EXPECTED_DATA_KEYS}
        gcn_submit = data.get('submit_to_gcn', False)
        tns_submit = data.get('submit_to_tns', False)
        serializer = self.serializer_class(data=data, context={'request': request})
        if serializer.is_valid():
            data = serializer.validated_data
            if non_serialized_data:
                if 'data' not in data:
                    data['data'] = {}
                data['data'].update(non_serialized_data)
            if tns_submit:
                try:
                    filenames = []
                    if 'files' in data:
                        filenames = submit_files_to_tns(data['files'])
                    tns_message = convert_hermes_message_to_tns(data, filenames)
                    object_name = submit_at_report_to_tns(tns_message)
                    if 'references' not in data['data']:
                        data['data']['references'] = []
                    data['data']['references'].append({
                        'source': 'tns_object',
                        'citation': object_name,
                        'url': urljoin(settings.TNS_BASE_URL, f'object/{object_name}')
                    })
                except BadTnsRequest as btr:
                    return Response({'error': str(btr)}, status.HTTP_400_BAD_REQUEST)
            try:
                if 'files' in data:
                    del data['files']
                if 'file_comments' in data:
                    del data['file_comments']
                message_uuid = submit_to_hop(request, data)
            except APIException as ae:
                return Response({'error': str(ae)}, status.HTTP_400_BAD_REQUEST)
            if gcn_submit:
                # TODO: I don't really know what we should do here if the GCN submission fails
                return submit_to_gcn(request, data, message_uuid)
            return Response({"message": f"Submitted message with uuid {message_uuid}"},
                            status=status.HTTP_200_OK)
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

    @action(detail=False, methods=['post'])
    def plaintext(self, request):
        plaintext_message = convert_to_plaintext(request.data)

        return Response(plaintext_message, status=status.HTTP_200_OK)


class GcnLoginRedirectView(View):
    pattern_name = 'gcn-login-redirect'

    def get(self, request, *args, **kwargs):
        redirect_uri = request.build_absolute_uri('/gcn-auth/authorize')
        return oauth.gcn.authorize_redirect(request, redirect_uri)


class GcnAuthorizeView(RedirectView):
    pattern_name = 'gcn-authorize'

    def get(self, request, *args, **kwargs):
        token = oauth.gcn.authorize_access_token(request)
        logger.info(f"Authorize View called with token: {token}")
        if token.get('userinfo', {}).get('existingIdp'):
            messages.error(request, 'GCN Authorization failed. Please try again using the same authentication method ' \
                           f'that was used to create your GCN account ({token["userinfo"]["existingIdp"]}).')
        else:
            update_token(request.user, OAuthToken.IntegratedApps.GCN, token)
        self.url = urljoin(f'{settings.HERMES_FRONT_END_BASE_URL}', 'profile')
        return super().get(request, *args, **kwargs)


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


class ProfileApiView(RetrieveAPIView):
    serializer_class = ProfileSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        logger.warning(f"user pk = {self.request.user.pk}, user = {self.request.user}")
        """Once authenticated, retrieve profile data"""
        qs = User.objects.filter(pk=self.request.user.pk).prefetch_related(
            'profile'
        )
        return qs.first().profile


class TNSOptionsApiView(RetrieveAPIView):
    """ View to retrieve the set of options for TNS submission, for the hermes UI to use """

    def get(self, request):
        return JsonResponse(data=get_tns_values())


class HeartbeatApiView(RetrieveAPIView):
    """ View to retrieve last timestamps for data received per stream """

    def get(self, request):
        last_timestamps = {
            'hop': cache.get('hop_stream_heartbeat')
        }
        return Response(last_timestamps)


class RevokeApiTokenApiView(APIView):
    """View to revoke an API token."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """A simple POST request (empty request body) with user authentication information in the HTTP header will revoke a user's API Token."""
        request.user.auth_token.delete()
        Token.objects.create(user=request.user)
        return Response({'message': 'API token revoked.'}, status=status.HTTP_200_OK)

    def get_endpoint_name(self):
        return 'revokeApiToken'


class RevokeHopCredentialApiView(APIView):
    """View to revoke this accounts Scimma Auth Hop Credential and create a new one."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """A simple POST request (empty request body) with user authentication information in the HTTP header will revoke the users hop credential."""
        username = request.user.get_username()
        hop_user_pk = request.user.profile.hop_user_pk
        credential_pk = request.user.profile.credential_pk
        credential_name = request.user.profile.credential_name
        if hopskotch.verify_credential_for_user(username, hop_user_pk, credential_name, credential_pk):
            hopskotch.delete_user_hop_credential_by_pk(hop_user_pk, credential_pk, hopskotch.get_user_api_token(username))
        hopskotch.regenerate_hop_credential(request.user)
        return Response({'message': 'Hop credential revoked and regenerated.'}, status=status.HTTP_200_OK)

    def get_endpoint_name(self):
        return 'revokeHopCredential'
