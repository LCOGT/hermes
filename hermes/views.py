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
from rest_framework.views import APIView
from rest_framework.decorators import action
from rest_framework import status, viewsets, filters
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

import jsons

from hop import Stream
from hop.auth import Auth

from hermes.brokers import hopskotch
from hermes.models import Message, Target, NonLocalizedEvent, NonLocalizedEventSequence
from hermes.forms import MessageForm
from hermes.utils import get_all_public_topics
from hermes.filters import MessageFilter, TargetFilter, NonLocalizedEventFilter, NonLocalizedEventSequenceFilter
from hermes.serializers import (MessageSerializer, TargetSerializer, NonLocalizedEventSerializer, GenericHermesMessageSerializer,
                                NonLocalizedEventSequenceSerializer, HermesCandidateSerializer, HermesPhotometrySerializer)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


def _extract_hop_auth(request) -> Auth:
    """Return a hop.Auth instance from either the request.header or the request.session.

    The reqeust.header takes precidence over the request.session.

    If this the request is comming from the HERMES front-end, then a hop.auth.Auth instance was inserted
    into the request's session dictionary upon logon in AuthenticationBackend.authenticate.
    This method extracts it. (`jsons` is used (vs. json) because Auth is non-trivial to
    serialize/deserialize, and the stdlib `json` package won't handle it correctly).

    If this this request is coming via the API, then a SCiMMA Auth SCRAM credential must be
    extracted from the request header and then used to instanciate the returned hop.Auth.
    """
    if 'SCIMMA-API-Auth-Username' in request.headers:
        # A SCiMMA Auth SCRAM credential came in request.headers. Use it to get hop.auth.Auth instance.
        username = request.headers['SCIMMA-API-Auth-Username']
        password = request.headers['SCIMMA-API-Auth-Password']
        hop_user_auth = Auth(username, password)
    else:
        # deserialize the hop.auth.Auth instance from the request.session
        hop_user_auth: Auth = jsons.load(request.session['hop_user_auth_json'], Auth)

    return hop_user_auth


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
    """This ViewSet does not have a Model backing it. It uses the SCiMMA Auth (Hop Auth) API
    to construct a response and return a dictionary:
        {
        'read': <topic list>,
        'write': <topic-list>,
        }
    """
    def list(self, request, *args, **kwargs) -> JsonResponse:
        """
        """
        username = request.user.username
        try:
            user_hop_auth: Auth = _extract_hop_auth(request)
        except KeyError as err:
            # This means no SCRAM creds were saved in this request's Session dict
            # TODO: what to do for HERMES Guest (AnonymousUser)
            logger.error(f'TopicViewSet {err}')
            all_topics = get_all_public_topics()
            default_topics = {
                'read': all_topics,
                'write': ['hermes.test'],
                }
            logger.error(f'TopicViewSet returning default topics: {default_topics}')
            return JsonResponse(data=default_topics)

        credential_name = user_hop_auth.username
        user_api_token = request.session['user_api_token']  # maintained in middleware

        topics = hopskotch.get_user_topic_permissions(username, credential_name, user_api_token,
                                                      exclude_groups=['sys'])
        logger.info(f'TopicViewSet.list topics for {username}: {topics}')

        response = JsonResponse(data=topics)
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
        hop_auth: Auth = _extract_hop_auth(request)
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
    serializer_class = GenericHermesMessageSerializer
    
    def get(self, request, *args, **kwargs):
        message = """This endpoint is used to send a generic hermes message
        
        Requests should be structured as below:
        
        {title: <Title of the message>,
         topic: <kafka topic to post message to>, 
         submitter: <submitter of the message>,
         authors: <Text full list of authors on a message>
         message_text: <Text of the message to send>,
         data: {<Unparsed json data dict>}
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
        """ Validate a RequestGrouo
        """
        serializer = self.serializer_class(data=request.data, context={'request': request})
        if serializer.is_valid():
            errors = {}
        else:
            errors = serializer.errors
        return Response(errors, status.HTTP_200_OK)


class SubmitCandidatesViewSet(SubmitHermesMessageViewSet):
    serializer_class = HermesCandidateSerializer

    def get(self, request, *args, **kwargs):
        message = """This endpoint is used to send a message with a list of potential candidates corresponding to a 
        non-localized event.
        
        Requests should be structured as below:
        
        {title: <Title of the message>,
         topic: <kafka topic to post message to>, 
         submitter: <submitter of the message>,
         authors: <Text full list of authors on a message>
         message_text: <Text of the message to send>,
         data: {
            event_id:  <ID of the non-localized event for these candidates>,
            extra_data: {<dict of key/value pairs of extra unparsed data>},
            candidates: [{target_name: <ID of the candidate target>,
                  ra: <Right Ascension in hh:mm:ss.ssss or decimal degrees>,
                  dec: <Declination in dd:mm:ss.ssss or decimal degrees>,
                  date: <Date/time of the candidate discovery>,
                  date_format: <Python strptime format string or "mjd" or "jd">,
                  telescope: <Discovery telescope>,
                  instrument: <Discovery instrument>,
                  band: <Wavelength band of the discovery observation>,
                  brightness: <Brightness of the candidate at discovery>,
                  brightness_error: <Brightness error of the candidate at discovery>,
                  brightness_unit: <Brightness units for the discovery, 
                                   current supported values: [AB mag, Vega mag]>
                           }, ...]
            }
        }
        """
        return Response({"message": message}, status.HTTP_200_OK)


class SubmitPhotometryViewSet(SubmitHermesMessageViewSet):
    serializer_class = HermesPhotometrySerializer

    def get(self, request, *args, **kwargs):
        message = """This endpoint is used to send a message to report photometry of one or more targets.
         
        Requests should be structured as below:

        {title: <Title of the message>,
         topic: <kafka topic to post message to>, 
         submitter: <submitter of the message>,
         authors: <Text full list of authors on a message>
         message_text: <Text of the message to send>,
         event_id: <ID of the non-localized event for these candidates>,
         data: {
            event_id: <ID of the non-localized event for these candidates>,
            extra_data: {<dict of key/value pairs of extra unparsed data>},
            photometry: [{target_name: <Name of the observed target>,
                  ra: <Right Ascension in hh:mm:ss.ssss or decimal degrees>,
                  dec: <Declination in dd:mm:ss.ssss or decimal degrees>,
                  date: <Date/time of the observation>,
                  date_format: <Python strptime format string or "mjd" or "jd">,
                  telescope: <Discovery telescope>,
                  instrument: <Discovery instrument>,
                  band: <Wavelength band of the discovery observation>,
                  brightness: <Brightness of the candidate at discovery>,
                  brightness_error: <Brightness error of the candidate at discovery>,
                  brightness_unit: <Brightness units for the discovery, 
                                   current supported values: [AB mag, Vega mag, mJy, and erg / s / cm² / Å]>
                           }, ...]
            }
        }
        """
        return Response({"message": message}, status.HTTP_200_OK)


class LoginRedirectView(RedirectView):
    pattern_name = 'login-redirect'

    def get(self, request, *args, **kwargs):

        logger.debug(f'LoginRedirectView.get -- request.user: {request.user}')

        login_redirect_url = f'{settings.HERMES_FRONT_END_BASE_URL}#/?user={request.user.email}'
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
