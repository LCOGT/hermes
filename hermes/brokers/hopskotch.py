"""hermes/brokers/hopskotch.py

Interaction with the HOPSKOTCH Kafka stream and it's associated APIs happen here.

After the SCIMMA_ADMIN_BASE_URL is defined in settings.py, this module encodes specifics
of the scimma_admin (hopauth) API that goes beyond that configuration. That is, this module
is intended depend on HOPSKOTCH/hopauth/scimma_admin specifics. For example, how the versioning
works, etc
"""
from http.client import responses
import json
import logging
import os
import requests

from django.conf import settings

from hop.auth import Auth

from rest_framework import status
from rest_framework.response import Response

import scramp


logger = logging.getLogger(__name__)
#logger.setLevel(logging.DEBUG)

#  from the environment, get the HERMES service account credentials for HopAuth (scimma-admin).
HOP_USERNAME = os.getenv('HOP_USERNAME', 'set the HOP_USENAME for the HERMES service account')
HOP_PASSWORD = os.getenv('HOP_PASSWORD', 'set the HOP_PASSWORD for the HERMES service account')

def get_hop_auth_api_url() -> str:
    """Use the HOP_AUTH_BASE_URL from settings.py and construct the API url from that.
    """
    # TODO: consider saving and re-using the version to save the network time

    # get the base url from the configuration in settings.py
    hop_auth_base_url = settings.HOP_AUTH_BASE_URL

    try:
        # get the current API version from the API
        version_url = hop_auth_base_url + '/api/version'
        response = requests.get(version_url, headers={'Content-Type': 'application/json'})
        # get the API version from response
        hop_auth_api_version = response.json()['current']
    except:
        hop_auth_api_version = 0

    hop_auth_api_url = hop_auth_base_url + f'/api/v{hop_auth_api_version}'
    logger.debug(f'get_hop_auth_api_url: hop_auth_api_url: {hop_auth_api_url}')
    return hop_auth_api_url


def get_hermes_hop_authorization() -> Auth:
    """return the hop.auth.Auth instance for the HERMES service account

    The HOP_USERNAME and HOP_PASSWORD environment variables are used and
    should enter the environmnet as k8s secrets.
    """
    username = os.getenv('HOP_USERNAME', None)
    password = os.getenv('HOP_PASSWORD', None)
    if username is None or password is None:
        error_message = 'Supply HERMES service account credentials: set HOP_USERNAME and HOP_PASSWORD environment variables.'
        logger.error(error_message)
        return Response({'message': 'HERMES service account credentials for HopAuth are not set correctly on the server'},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    hop_auth: Auth = Auth(username, password)
    return hop_auth


def get_hermes_api_token(scram_username, scram_password) -> str:
    """return the Hop Auth API token for the HERMES service account
    """
    hop_auth_api_url = get_hop_auth_api_url()

    # Peform the first round of the SCRAM handshake:
    client = scramp.ScramClient(["SCRAM-SHA-512"], scram_username, scram_password)
    client_first = client.get_client_first()
    logger.debug(f'SCRAM client first request: {client_first}')

    scram_resp1 = requests.post(hop_auth_api_url + '/scram/first',
                                json={"client_first": client_first},
                                headers={"Content-Type":"application/json"})
    logger.debug(f'SCRAM server first response: {scram_resp1.json()}')

    # Peform the second round of the SCRAM handshake:
    client.set_server_first(scram_resp1.json()["server_first"])
    client_final = client.get_client_final()
    logger.debug(f'SCRAM client final request: {client_final}')

    scram_resp2 = requests.post(hop_auth_api_url + '/scram/final',
                                json={"client_final": client_final},
                                headers={"Content-Type":"application/json"})
    logger.debug(f'SCRAM server final response: {scram_resp2.json()}')

    client.set_server_final(scram_resp2.json()["server_final"])

    # Get the token we should have been issued:
    hermes_api_token = scram_resp2.json()["token"]
    logger.debug(f'get_hermes_api_token: Token issued: {hermes_api_token}')
    hermes_api_token = f'Token {hermes_api_token}'  # Django wants this (Token<space>) prefix
    return hermes_api_token


def get_user_hop_authorization(vo_person_id, user_api_token=None) -> Auth:
    """return the hop.auth.Auth instance for the user with the given vo_person_id
    """
    if user_api_token is None:
        user_api_token = get_user_api_token(vo_person_id)

    def _get_hop_user_pk() -> int:
        """return the primary key of this user from the Hop Auth API

        vo_person_id's are assigned by COLogon and are of the form SCiMM1000000.
        The api/v0/users API endpoint returns a list of user dictionaries with
        keys of (pk, username, email), where the username is to vo_person_id
        """
        # request the list of users from the Hop Auth API
        users_url = get_hop_auth_api_url() + '/users'
        response = requests.get(users_url,
                                headers={'Authorization': user_api_token,
                                         'Content-Type': 'application/json'})
        # from the response, extract the list of user dictionaries
        hop_users = response.json()
        # find the user dict whose username matches our vo_person_id
        # this is the idiom for searchng a list of dictionaries for certain key-value (username)
        hop_user = next((item for item in hop_users if item['username'] == vo_person_id), None)
        if hop_user is not None:
            hop_user_pk = hop_user['pk']
            logger.debug(f'get_user_hop_authorization._get_hop_user_pk: PK for {vo_person_id} is {hop_user_pk}')
        else:
            logger.error(f'get_user_hop_authorization._get_hop_user_pk: Can not find user {vo_person_id} in Hop Auth users.')
            hop_user_pk = None

        return hop_user_pk

    # Construct URL to create Hop Auth SCRAM credentials for this user
    hop_user_pk = _get_hop_user_pk()  # need the pk for the URL
    user_credentials_url = get_hop_auth_api_url() + f'/users/{hop_user_pk}/credentials'
    logger.debug(f'get_user_hop_authorization user_credentials URL: {user_credentials_url}')

    logger.info(f'get_user_hop_authorization Creating SCRAM credentials for user {vo_person_id}')
    user_credentials_response = requests.post(user_credentials_url,
                                              data=json.dumps({'description': 'Created by HERMES'}),
                                              headers={'Authorization': user_api_token,
                                                       'Content-Type': 'application/json'})
    logger.debug(f'HopAuthTestView user_credentials_response.json(): {user_credentials_response.json()}')

    user_hop_username = user_credentials_response.json()['username']
    user_hop_password = user_credentials_response.json()['password']

    # you can never again get this SCRAM credential, so save it somewhere (like the Session)
    user_hop_authorization: Auth = Auth(user_hop_username, user_hop_password)

    logger.debug(f'get_user_hop_authorization - new SCRAM creds for {vo_person_id} username: {user_hop_username} password: {user_hop_password}')

    return user_hop_authorization


def get_user_api_token(vo_person_id, hermes_api_token=None):
    """return a Hop Auth API token for the given user.
    
    You need an API token to get the user API token and that's what the
    HERMES service account is for. Use the hermes_api_token (the API token
    for the HERMES service account), to get the API token for the user with
    the given vo_person_id. If the hermes_api_token isn't passed in, get one.
    """
    if hermes_api_token is None:
        # to get the service account API token, we need SCRAM credentials for
        hermes_hop_auth: Auth = get_hermes_hop_authorization()
        # use the SCRAM creds to get the service account API token
        hermes_api_token = get_hermes_api_token(hermes_hop_auth.username, hermes_hop_auth.password)

    # Set up the URL
    # see scimma-admin/scimma_admin/hopskotch_auth/urls.py (scimma-admin is Hop Auth repo)
    token_for_user_url = get_hop_auth_api_url() + '/oidc/token_for_user'

    # Set up the request data
    # the vo_person_id comes from the request.user.username for CILogon-created
    # (OIDC Provider-created) User instances. It is the vo_person_id from CILogon
    # that Hop Auth (scimma-admin) is looking for.
    # see scimma-admin/scimma_admin.hopskotch_auth.api_views.TokenForOidcUser
    hop_auth_request_data = {
        'vo_person_id': vo_person_id,
    }

    # Make the request and extract the user api token from the response
    response = requests.post(token_for_user_url,
                             data=json.dumps(hop_auth_request_data),
                             headers={'Authorization': hermes_api_token,
                                      'Content-Type': 'application/json'})

    if response.status_code == 200:
        # get the user API token out of the response
        token_info = response.json()
        user_api_token = token_info['token']
        user_api_token = f'Token {user_api_token}'  # Django wants a 'Token ' prefix
        user_api_token_expiration_date_as_str = token_info['token_expires'] # TODO: convert to datetime.datetime

        logger.debug(f'get_user_api_token vo_person_id: {vo_person_id}')
        logger.debug(f'get_user_api_token user_api_token: {user_api_token}')
        logger.debug(f'get_user_api_token user_api_token Expires: {user_api_token_expiration_date_as_str}')
    else:
        logger.error((f'HopAuthTestView hopskotch_auth_response.status_code: '
                      f'{responses[response.status_code]} [{response.status_code}]'))
        user_api_token = None # this is a problem

    return user_api_token

