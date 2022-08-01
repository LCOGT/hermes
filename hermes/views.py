from http.client import responses
import json
import logging
import os

# this is for OIDC experimentation
from django.contrib.auth.models import User

from django.views.decorators.csrf import csrf_exempt
from django.views.generic import ListView, DetailView, FormView, RedirectView
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

import requests
import scramp

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


def get_hermes_hop_authorization():
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

    return hop_auth


def submit_to_hop(message):
    hop_auth = get_hermes_hop_authorization()

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

class HopAuthTestView(RedirectView):
    pattern_name = 'index'

    def _get_rest_token(self, scimma_admin_api_url, scram_username, scram_password):
        # TODO: this whole method should be refactored; it doesn't have to be an instance method

        # this is the scimma-admin crdential created locally (127.0.0.1:8000)
        # that corresponds to the user defined in scimma-admin/user_data_test-admin
        # test-admin-4150ad45
        # KZiGHUl3vSpaNxRAZxKxGci3RprTZ72O

        # Peform the first round of the SCRAM handshake:
        client = scramp.ScramClient(["SCRAM-SHA-512"], scram_username, scram_password)
        client_first = client.get_client_first()
        # print("SCRAM client first request:", client_first)
        scram_resp1 = requests.post(scimma_admin_api_url + '/scram/first',
                                    json={"client_first": client_first},
                                    headers={"Content-Type":"application/json"})
        # print("SCRAM server first response:", scram_resp1.json())
        
        # Peform the second round of the SCRAM handshake:
        client.set_server_first(scram_resp1.json()["server_first"])
        client_final = client.get_client_final()
        logger.debug(f'SCRAM client final request: {client_final}')

        scram_resp2 = requests.post(scimma_admin_api_url + '/scram/final',
                                    json={"client_final": client_final},
                                    headers={"Content-Type":"application/json"})
        logger.debug(f'SCRAM server final response: {scram_resp2.json()}')

        client.set_server_final(scram_resp2.json()["server_final"])

        # Get the token we should have been issued:
        rest_token = scram_resp2.json()["token"]
        logger.info(f'_get_rest_token: Token issued: {rest_token}')
        rest_token = f'Token {rest_token}'  # Django wants this prefix
        return rest_token


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

        hop_auth_api_url = hopskotch.get_hop_auth_api_url()
        logger.info(f'HopAuthTestView hop_auth_api_url: {hop_auth_api_url}')

        # 1. get the HERMES SCRAM credential (i.e. HOP_USERNAME, HOP_PASSWORD)
        hop_auth = get_hermes_hop_authorization()

        logger.info(f'HopAuthTestView hop_auth: {hop_auth}')
        logger.info(f'HopAuthTestView hop_auth.username: {hop_auth.username}')
        logger.info(f'HopAuthTestView hop_auth.password: {hop_auth.password}')

        # TODO: make sure this test data is all consistent
        # for testing purposes reset username and password to match
        # the credentials created locally for the test-admin user
        # (test-admin@example.com supplied by scimma-admin and netcat: (nc -l 8002 < user_data_test-admin)
        # test-admin-4150ad45
        # KZiGHUl3vSpaNxRAZxKxGci3RprTZ72O
        test_hop_username = 'test-admin-4150ad45'
        test_hop_password = 'KZiGHUl3vSpaNxRAZxKxGci3RprTZ72O'

        logger.info('HopAuthTestView Using SCRAM creds for user_data_test-admin:')
        logger.info(f'HopAuthTestView hop_aut.username: {test_hop_username}')
        logger.info(f'HopAuthTestView hop_aut.password: {test_hop_password}')

        # 2. Do a SCRAM exchange (/scram/first + /scram/final to get a REST API Token (hermes_api_token)
        #hermes_api_token = self._get_rest_token(scimma_admin_api_url, hop_auth.username, hop_auth.password)
        hermes_api_token = self._get_rest_token(scimma_admin_api_url, test_hop_username, test_hop_password)
        logger.info(f'HopAuthTestView hermes_api_token: {hermes_api_token}')

        # 3. Use the REST API Token (hermes_api_token) to call /oidc/token_for_user for the logged on User (user_api_token)

        # 3.A. Set up the URL
        # see scimma-admin/scimma_admin/hopskotch_auth/urls.py
        scimma_admin_token_for_user_api_suffix = '/oidc/token_for_user'
        token_for_user_url = scimma_admin_api_url + scimma_admin_token_for_user_api_suffix
        logger.info(f'HopAuthTestView token_for_user URL: {token_for_user_url}')

        # 3.B. Set up the request data
        # the request.user.username for CILogon-created (OIDC Provider-created) User insetances
        # is the vo_person_id from CILogon that scimma-admin is looking for.
        # see scimma-admin/scimma_admin.hopskotch_auth.api_views.TokenForOidcUser
        hopskotch_auth_request_data = {
            #'vo_person_id': request.user.username,
            'vo_person_id': 'SCiMMA2000002',  ## test value from user_data_test-admin
        }
        logger.info(f'HopAuthTestView request.user.username: {request.user.username} -> SCiMMA2000002 from user_data_test-admin')
        logger.debug(f'HopAuthTestView request_data: {hopskotch_auth_request_data}')

        # 3.C Make the request and extract the user api token from the response
        hopskotch_auth_response = requests.post(token_for_user_url,
                                                data=json.dumps(hopskotch_auth_request_data),
                                                headers={'Authorization': hermes_api_token,
                                                         'Content-Type': 'application/json'})

        logger.debug(f'HopAuthTestView hopskotch_auth_response: {hopskotch_auth_response}')
        logger.debug(f'HopAuthTestView hopskotch_auth_response.status_code: {hopskotch_auth_response.status_code}')
        logger.debug(f'HopAuthTestView hopskotch_auth_response.content: {hopskotch_auth_response.content}')  # <class 'bytes'>
        logger.debug(f'HopAuthTestView hopskotch_auth_response.text: {hopskotch_auth_response.text}')  # <class 'str'>

        if hopskotch_auth_response.status_code == 200:
            logger.info(f'HopAuthTestView hopskotch_auth_response.status_code: {hopskotch_auth_response.status_code}')
            logger.info(f'HopAuthTestView hopskotch_auth_response.json(): {hopskotch_auth_response.json()}')  # <class 'dict'>
            # get the user API token out of the response
            token_info = hopskotch_auth_response.json()
            user_api_token = token_info['token']
            user_api_token_expiration_date_as_str = token_info['token_expires'] # TODO: convert to datetime.datetime
            user_api_token = f'Token {user_api_token}'  # Django wants a 'Token ' prefix
            logger.info(f'HopAuthTestView user_api_token: {user_api_token}')
        else:
            logger.error((f'HopAuthTestView hopskotch_auth_response.status_code: '
                          f'{responses[hopskotch_auth_response.status_code]} [{hopskotch_auth_response.status_code}]'))

        # 4. Use the user_api_token (step #3) to get topics, publish to/subscribe to topics
        #
        # 4.A Try to get the test-admin user's groups and topics
        scimma_admin_token_for_user_api_suffix = '/oidc/token_for_user'
        token_for_user_url = scimma_admin_api_url + scimma_admin_token_for_user_api_suffix
        logger.info(f'HopAuthTestView token_for_user URL: {token_for_user_url}')

        # there queries just test that the /oidc/token_for_user user_api_token works
        if False:
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


        # TODO: this (4.B) should have happened earlier in this process and the
        #   hermes_api_token and it's SCRAM creads should be distinct from
        #   the users SCRAM creds that we use to get hop.auth.Auth and
        #   hop.Stream instances and publish to Hopskotch
        # 4.B Create SCRAM credentials (username/password for User)
        # endpoint is CREATE method of hopauth/api/v0/users/<PK>/credentials

        # TODO: find this user in the /users list
        # this is the user with the vo_person_id that came back from CILogon
        # which should be part of this requests user instance (user.username?)
        user_pk = 1  # TODO: this is just for now

        scimma_admin_user_credentials_api_suffix = f'/users/{user_pk}/credentials'
        user_credentials_url = scimma_admin_api_url + scimma_admin_user_credentials_api_suffix
        logger.info(f'HopAuthTestView user_credentials URL: {user_credentials_url}')

        user_credentials_response = requests.post(user_credentials_url,
                                                  data=json.dumps({'description': 'Created by HERMES'}),
                                                  headers={'Authorization': user_api_token,
                                                           'Content-Type': 'application/json'})
        logger.info(f'HopAuthTestView user_credentials_response.json(): {user_credentials_response.json()}')
        # we can never again get this SCRAM credential, so save it somewhere
        hop_username = user_credentials_response.json()['username']
        hop_password = user_credentials_response.json()['password']

        # TODO: Here is where we would call
        # hop_auth = Auth(username, password)
        # and
        # stream = Stream(auth=hop_auth)
        # and write to the Kafka stream

        clean_up_SCRAM_cred = True
        if clean_up_SCRAM_cred:
            # find the <PK> of the SCRAM credential just issued
            user_credentials_response = requests.get(user_credentials_url,
                                                     headers={'Authorization': user_api_token,
                                                              'Content-Type': 'application/json'})
            # from the response, extract the list of user credential dictionaries
            user_creds = user_credentials_response.json()
            # this is the idiom for searchng a list of dictionaries for certain key-value (username)
            user_cred = next((item for item in user_creds if item["username"] == hop_username), None)
            if user_cred is not None:
                scram_pk = user_cred['pk']
                scimma_admin_user_credentials_detail_api_suffix = f'/users/{user_pk}/credentials/{scram_pk}'
                user_credentials_detail_url = scimma_admin_api_url + scimma_admin_user_credentials_detail_api_suffix
                logger.info(f'HopAuthTestView SCRAM cred: {user_cred}')
                logger.info(f'HopAuthTestView user_credentials_detail_url: {user_credentials_detail_url}')
                user_credentials_delete_response = requests.delete(user_credentials_detail_url,
                                                     headers={'Authorization': user_api_token,
                                                              'Content-Type': 'application/json'})
                logger.info(
                    (f'HopAuthTestView user_credentials_delete_response: {responses[user_credentials_delete_response.status_code]}',
                     f'[{user_credentials_delete_response.status_code}]'))
            else:
                logger.error(f'HopAuthTestView can not clean up SCRAM credential: {hop_username} not found in {user_creds}')
            
        return super().get(request)

def test_query(user_api_token, query_path):
    resp = requests.get(f'http://127.0.0.1:8000/hopauth/api/v0{query_path}',
                        headers={'Authorization': user_api_token,
                                 'Content-Type': 'application/json'})
    if len(resp.text)>0:
        #logger.info(f'GET {query_path} [{resp.status_code}]: {resp.json()}')
        logger.info(f'GET {query_path} [{resp.status_code}]: {resp.text}')
    else:
        logger.info(f'GET {query_path} [{resp.status_code}]')

