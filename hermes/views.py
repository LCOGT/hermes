from http.client import responses
import json
import logging

# this is for OIDC experimentation
from django.contrib.auth.models import User
from django.contrib.sessions.models import Session
from django.contrib.sessions.backends.db import SessionStore

from django.views.decorators.csrf import csrf_exempt
from django.views.generic import ListView, DetailView, FormView, RedirectView
from django.urls import reverse_lazy
from django.shortcuts import redirect
from rest_framework.views import APIView
from rest_framework import status
from rest_framework.response import Response

from astropy.coordinates import SkyCoord
from astropy import units
import jsons
from marshmallow import Schema, fields, ValidationError, validates_schema

from hop import Stream
from hop.auth import Auth

import requests

from rest_framework import viewsets

from hermes.brokers import hopskotch
from hermes.models import Message
from hermes.forms import MessageForm
from hermes.serializers import MessageSerializer


logger = logging.getLogger(__name__)
#logger.setLevel(logging.DEBUG)


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


def submit_to_hop(request, message):
    """Open the Hopskotch kafka stream for write and publish an Alert

    The request holds the Session dict which has the 'hop_user_auth_json` key
    whose value can be deserialized into a hop.auth.Auth instance to open the
    stream with. (The hop.auth.Auth instance was added to the Session dict upon
    logon via the HopskotchOIDCAuthenticationBackend.authenticate method).
    """
    try:
        # the hop.auth.Auth requires jsons for non-trivial serialization/deserialization
        hop_auth: Auth = jsons.load(request.session['hop_user_auth_json'], Auth)
    except KeyError as err:
        logger.error(f'Hopskotch Authorization for User {request.user.username} not found.  err: {err}')
        # TODO: REMOVE THE FOLLOEING CODE AFTER TESTING!!
        # use the Hermes service account temporarily while testing...
        logger.warning(f'Submitting with Hermes service account authorization (testing only)')
        hop_auth: Auth = hopskotch.get_hermes_hop_authorization()


    # TODO: provide some indication of the User/vo_person_id submitting the message
    logger.info(f'submit_to_hop User {request.user} with credentials {hop_auth.username}')

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
    #@csrf_exempt
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
        return submit_to_hop(request, request.data)

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

        return submit_to_hop(request, vars(candidates))

class HopAuthTestView(RedirectView):
    pattern_name = 'index'

    def get(self, request, *args, **kwargs):

        # logger.info(f'HopAuthTestView request: {request}')
        # logger.info(f'HopAuthTestView request dir: {dir(request)}')
        # logger.info(f'HopAuthTestView request User: {request.user}')
        # logger.info(f'HopAuthTestView request User dir: {dir(request.user)}')
        # logger.info(f'HopAuthTestView request.session: {request.session}')
        # logger.info(f'HopAuthTestView request.session dir: {dir(request.session)}')

        # 1. get the HERMES SCRAM credential (i.e. HOP_USERNAME, HOP_PASSWORD)
        # 2. Do a SCRAM exchange (/scram/first + /scram/final to get a REST API Token (hermes_api_token)
        # 3. Use the REST API Token (hermes_api_token) to call /oidc/token_for_user for the logged on User (user_api_token)
        # 4. Use the user_api_token (step #3) to get topics, publish to/subscribe to topics
        # 

        # reminder about PORTS
        # 8000: local scimma-admin
        # 8001: local hermes
        # 8002: local netcat (nc) (spoofed CILogon)
        # 5433: dockerized scimma-admin-postgres
        # 5432: dockerized hermes-postgres

        # 0. preliminaries
        # scimma_admin_base_url = 'http://127.0.0.1:8000/hopauth'  # TODO: configure this in settings.py/local_settings.py
        # scimma_admin_api_version = 0  # TODO get from scimma_admin_base_url+'/api/version
        # scimma_admin_api_url = scimma_admin_base_url + f'/api/v{scimma_admin_api_version}'

        #
        # Explore the Django Session instance that is part of the request
        #

##         sessions = Session.objects.all()
##         logger.info(f'HopAuthTestView There are {sessions.count()} sessions:')
##         for session in sessions:
##             logger.info(f'HopAuthTestView session {session}')
## 
##         logger.info(f'HopAuthTestView request.session.session_key: {request.session.session_key}')
##         logger.info(f'HopAuthTestView request.session: {request.session}')
##         for session_key in request.session.keys():
##             logger.info(f'HopAuthTestView request.session[{session_key}]: {request.session[session_key]}')
## 
##         hop_auth_api_url = hopskotch.get_hop_auth_api_url()
##         logger.debug(f'HopAuthTestView hop_auth_api_url: {hop_auth_api_url}')
## 

        # 1. get the HERMES SCRAM credential (i.e. HOP_USERNAME, HOP_PASSWORD)
        #    for the HERMES service acount
        hop_auth: Auth = hopskotch.get_hermes_hop_authorization()
        logger.debug(f'HopAuthTestView Using SCRAM creds for HERMES Service Account: {hop_auth.username}')

        # 2. Do a SCRAM exchange (/scram/first + /scram/final) to get a REST API Token (hermes_api_token)
        hermes_api_token = hopskotch.get_hermes_api_token(hop_auth.username, hop_auth.password)
        logger.debug(f'HopAuthTestView hermes_api_token: {hermes_api_token}')

        # 3. Use the REST API Token (hermes_api_token) to call /oidc/token_for_user for the logged on User (user_api_token)
        user_api_token = hopskotch.get_user_api_token(vo_person_id=request.user.username,
                                                      hermes_api_token=hermes_api_token)

        # 4. Use the user_api_token (step #3) to get topics, publish to/subscribe to topics

        # these queries just test that the /oidc/token_for_user user_api_token work
        #test_query(user_api_token, '/users')
        #test_query(user_api_token, '/scram_credentials') # 73 is llindstrom
        test_query(user_api_token, '/users/73/credentials')
        do_all_tests = False
        if do_all_tests:
            test_query(user_api_token, '/users')
            test_query(user_api_token, '/groups')
            test_query(user_api_token, '/scram_credentials')
            test_query(user_api_token, "/users/1")
            test_query(user_api_token, "/users/1/memberships")
            test_query(user_api_token, "/users/1/credentials")
            test_query(user_api_token, "/users/1/credentials/1")
            test_query(user_api_token, "/users/1/credentials/1/permissions")
            test_query(user_api_token, "/topics")
            test_query(user_api_token, "/topics/1")
            test_query(user_api_token, "/topics/1/permissions")
            test_query(user_api_token, "/groups")
            test_query(user_api_token, "/groups/1")
            test_query(user_api_token, "/groups/1/members")
            test_query(user_api_token, "/groups/1/topics")
            test_query(user_api_token, "/groups/1/topics/1")
            test_query(user_api_token, "/groups/1/topics/1/permissions")
            test_query(user_api_token, "/groups/1/permissions_given")
            test_query(user_api_token, "/groups/1/permissions_received")

        # hop_user_auth_json added to Session dict in AuthenticationBackend.authenticate
        hop_user_auth: Auth = jsons.load(request.session['hop_user_auth_json'], Auth)
        logger.info(f'HopAuthTestView Extracted Auth from Session: username: {hop_user_auth.username} password: {hop_user_auth.password}')

        hop_user_auths = hopskotch.get_user_hop_authorizations(request.user.username)

        clean_up_SCRAM_cred = True
        if clean_up_SCRAM_cred:
            logger.info(f'HopAuthTestView Deleting  hop_user_authorization: username: {hop_user_auth.username}')
            hopskotch.delete_user_hop_authorization(request.user.username,hop_user_auth)
            logger.info(f'HopAuthTestView Finished deleting  hop_user_authorization: username: {hop_user_auth.username}')

        hop_user_auths = hopskotch.get_user_hop_authorizations(request.user.username)

        return super().get(request)

def test_query(user_api_token, query_path):
    resp = requests.get(f'{hopskotch.get_hop_auth_api_url()}{query_path}',
                        headers={'Authorization': user_api_token,
                                 'Content-Type': 'application/json'})
    if len(resp.text)>0:
        #logger.info(f'GET {query_path} [{resp.status_code}]: {resp.json()}')
        logger.info(f'GET {query_path} [{resp.status_code}]: {resp.text}')
    else:
        logger.info(f'GET {query_path} [{resp.status_code}]')

