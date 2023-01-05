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
from hermes.serializers import (MessageSerializer, TargetSerializer, NonLocalizedEventSerializer, GenericHermesMessageSerializer,
                                NonLocalizedEventSequenceSerializer, HermesDiscoverySerializer, HermesPhotometrySerializer,
                                ProfileSerializer)

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
        """ Validate a Message Schema
        """
        serializer = self.serializer_class(data=request.data, context={'request': request})
        if serializer.is_valid():
            errors = {}
        else:
            errors = serializer.errors
        return Response(errors, status.HTTP_200_OK)


class SubmitDiscoveriesViewSet(SubmitHermesMessageViewSet):
    serializer_class = HermesDiscoverySerializer

    def get(self, request, *args, **kwargs):
        message = """This endpoint is used to send a message with a list of potential Discoveries corresponding to a 
        non-localized event.
        
        Requests should be structured as below:
        
        {title: <Title of the message>,
         topic: <kafka topic to post message to>, 
         submitter: <submitter of the message>,
         authors: <Text full list of authors on a message>
         message_text: <Text of the message to send>,
         data: {
            event_id:  <ID of the non-localized event for these discoveries if applicable>,
            type: <The type of this discovery, i.e. GRB or SN, etc.>,
            extra_data: {<dict of key/value pairs of extra unparsed data>},
            photometry: [{target_name: <ID of the discovery target>,
                  ra: <Right Ascension in hh:mm:ss.ssss or decimal degrees>,
                  dec: <Declination in dd:mm:ss.ssss or decimal degrees>,
                  date: <Date/time of the discovery discovery>,
                  date_format: <Python strptime format string or "mjd" or "jd">,
                  telescope: <Discovery telescope>,
                  instrument: <Discovery instrument>,
                  band: <Wavelength band of the discovery observation>,
                  brightness: <Brightness of the discovery>,
                  nondetection: <Boolean of if this observation corresponds to a nondetection or not>,
                  brightness_error: <Brightness error of the discovery>,
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
         data: {
            event_id: <ID of the non-localized event for these observation if applicable>,
            extra_data: {<dict of key/value pairs of extra unparsed data>},
            photometry: [{target_name: <Name of the observed target>,
                  ra: <Right Ascension in hh:mm:ss.ssss or decimal degrees>,
                  dec: <Declination in dd:mm:ss.ssss or decimal degrees>,
                  date: <Date/time of the observation>,
                  date_format: <Python strptime format string or "mjd" or "jd">,
                  telescope: <Discovery telescope>,
                  instrument: <Discovery instrument>,
                  band: <Wavelength band of the discovery observation>,
                  brightness: <Brightness of the observation>,
                  nondetection: <Boolean of if this observation corresponds to a nondetection or not>,
                  brightness_error: <Brightness error of the observation>,
                  brightness_unit: <Brightness units for the discovery, 
                                   current supported values: [AB mag, Vega mag, mJy, and erg / s / cm² / Å]>
                           }, ...]
            }
        }
        """
        return Response({"message": message}, status.HTTP_200_OK)


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
