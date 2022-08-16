"""hermes/brokers/hopskotch.py

Interaction with the HOPSKOTCH Kafka stream and it's associated APIs happen here.

After the SCIMMA_ADMIN_BASE_URL is defined in settings.py, this module encodes specifics
of the scimma_admin (hopauth) API that goes beyond that configuration. That is, this module
is intended depend on HOPSKOTCH/hopauth/scimma_admin specifics. For example, how the versioning
works, etc

The top level functions are:
  * authorize_user()
  * deauthorize_user()

Lower level and utility functions:
  * TODO: make function glossary
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
logger.setLevel(logging.DEBUG)

#  from the environment, get the HERMES service account credentials for HopAuth (scimma-admin).
HOP_USERNAME = os.getenv('HOP_USERNAME', 'set the HOP_USENAME for the HERMES service account')
HOP_PASSWORD = os.getenv('HOP_PASSWORD', 'set the HOP_PASSWORD for the HERMES service account')

def get_hop_auth_api_url(api_version=None) -> str:
    """Use the HOP_AUTH_BASE_URL from settings.py and construct the API url from that.
    """
    # get the base url from the configuration in settings.py
    hop_auth_base_url = settings.HOP_AUTH_BASE_URL

    if api_version is None:
        try:
            # get the current API version from the API
            version_url = hop_auth_base_url + '/api/version'
            response = requests.get(version_url, headers={'Content-Type': 'application/json'})
            # get the API version from response
            hop_auth_api_version = response.json()['current']
        except:
            hop_auth_api_version = 0
    else:
        hop_auth_api_version = api_version

    hop_auth_api_url = hop_auth_base_url + f'/api/v{hop_auth_api_version}'
    logger.debug(f'get_hop_auth_api_url: hop_auth_api_url: {hop_auth_api_url}')
    return hop_auth_api_url


def get_hermes_hop_authorization() -> Auth:
    """return the hop.auth.Auth instance for the HERMES service account

    The HOP_USERNAME and HOP_PASSWORD environment variables are used and
    should enter the environmnet as k8s secrets.
    """
    # TODO: I think this can use the module level variables (set above)
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


def authorize_user(user: str) -> Auth:
    """Set up user for all Hopskotch interactions.
    (Should be called upon logon (probably via OIDC authenticate)

    * adds user to hermes group
    * creates user SCRAM credential (hop.auth.Auth instance)
    * add hermes.test topic permissions to SCRAM credential
    * returns hop.auth.Auth to authenticate() for inclusion in Session dictionary
    """
    logger.info(f'authorize_user user: {user}')
    user_api_token = get_user_api_token(user)
    user_pk = _get_hop_user_pk(user, user_api_token=user_api_token)

    # Only Hop Auth admins can add users to groups and permissions to credentials.
    # So, get the hermes_api_token for Authorization to do those things below.
    hermes_api_token = get_hermes_api_token(HOP_USERNAME, HOP_PASSWORD)

    # TODO: this should probably be factored out into it's own function
    # Add the user to the hermes group
    group_name = 'hermes'
    group_pk = _get_hop_group_pk(group_name, user_api_token=user_api_token)

    # if user is already in hermes group, don't add
    user_groups = get_user_groups(user, user_api_token=user_api_token)

    if not group_name in user_groups:
        # add the user
        group_add_url = get_hop_auth_api_url() +  f'/groups/{group_pk}/members'
        logger.debug(f'authorize_user group_add_url: {group_add_url}')
        group_add_request_data = {
            'user':  user_pk,
            'group': group_pk,
            'status': 1,  # Member=1, Owner=2
        }
        group_add_response = requests.post(group_add_url,
                                           json=group_add_request_data,
                                           headers={'Authorization': hermes_api_token,
                                                    'Content-Type': 'application/json'})
        logger.debug(f'authorize_user group_add_response: {group_add_response}, {dir(group_add_response)}')
        logger.debug(f'authorize_user group_add_response.reason: {group_add_response.reason}')
        logger.debug(f'authorize_user group_add_response.text: {group_add_response.text}')
    else:
        logger.info(f'authorize_user User {user} already a member of group {group_name}')

    # create user SCRAM credential (hop.auth.Auth instance)
    user_hop_auth: Auth = get_user_hop_authorization(user)
    credential_pk = _get_hop_credential_pk(user, user_hop_auth, user_pk=user_pk, user_api_token=user_api_token)

    topic_name = 'hermes.test'
    topic_pk = _get_hop_topic_pk(topic_name, user_api_token)
    # TODO: add hermes.test topic permissions to the new SCRAM credential
    #credential_permission_url = get_hop_auth_api_url() +  f'/groups/{group_pk}/topics/{topic_pk}/permissions'
    credential_permission_url = get_hop_auth_api_url() +  f'/users/{user_pk}/credentials/{credential_pk}/permissions'
    logger.debug(f'authorize_user credential_permission_url: {credential_permission_url}')
    credential_permission_request_data = {
        'principal':  credential_pk,  # TODO: it seems like this has to be the credential PK
        'topic': topic_pk,
        'operation': 1,  # All=1, Read=2, Write=3, etc, etc
    }
    credential_permission_response = requests.post(credential_permission_url,
                                                   json=credential_permission_request_data,
                                                   headers={'Authorization': hermes_api_token,
                                                            'Content-Type': 'application/json'})
    logger.debug(f'authorize_user credential_permission_response:        {credential_permission_response}')
    logger.debug(f'authorize_user credential_permission_response.reason: {credential_permission_response.reason}')
    logger.debug(f'authorize_user credential_permission_response.text:   {credential_permission_response.text}')

    return user_hop_auth


def deauthorize_user(username, user_hop_auth):
    """Remove from Hop Auth the SCRAM credentials (user_hop_auth) that were created
    for this session.

    This should be called from the OIDC_OP_LOGOUT_URL_METHOD, upon HERMES logout.
    """
    logger.debug(f'deauthorize_user user: {username} auth: {user_hop_auth.username}')
    delete_user_hop_authorization(username, user_hop_auth)


def _get_hop_user_pk(vo_person_id, user_api_token) -> int:
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
        logger.debug(f'_get_hop_user_pk: PK for {vo_person_id} is {hop_user_pk}')
    else:
        hop_user_pk = None
        logger.error(f'_get_hop_user_pk: Can not find user {vo_person_id} in Hop Auth users.')

    return hop_user_pk

def _get_hop_group_pk(group_name, user_api_token) -> int:
    """return the primary key of the given group from the Hop Auth API
    """
    # request the list of groups from the Hop Auth API
    groups_url = get_hop_auth_api_url() + '/groups'
    response = requests.get(groups_url,
                            headers={'Authorization': user_api_token,
                                     'Content-Type': 'application/json'})
    # example group dictionary: {'pk': 1, 'name': 'gcn', 'description': ''}
    # from the response, extract the list of group dictionaries
    hop_groups = response.json()

    # find the group dict whose name matches our group_name
    # this is the idiom for searchng a list of dictionaries for certain key-value (group_name)
    hop_group = next((item for item in hop_groups if item['name'] == group_name), None)
    if hop_group is not None:
        hop_group_pk = hop_group['pk']
        logger.debug(f'_get_hop_group_pk: PK for group {group_name} is {hop_group_pk}')
    else:
        hop_group_pk = None
        logger.error(f'_get_hop_group_pk: Can not find group {group_name} in Hop Auth groups.')

    return hop_group_pk

def _get_hop_topic_pk(topic_name, user_api_token) -> int:
    """return the primary key of the given topic from the Hop Auth API
    """
    # request the list of topicss from the Hop Auth API
    topics_url = get_hop_auth_api_url() + '/topics'
    response = requests.get(topics_url,
                            headers={'Authorization': user_api_token,
                                     'Content-Type': 'application/json'})
    # example topic dictionary:
    # {'pk': 84, 'owning_group': 10, 'name': 'lvalert-dev.external_snews',
    #  'publicly_readable': False, 'description': ''}
    # from the response, extract the list of topic dictionaries
    hop_topics = response.json()

    # find the topic dict whose name matches our topic_name
    # this is the idiom for searchng a list of dictionaries for certain key-value (topic_name)
    hop_topic = next((item for item in hop_topics if item['name'] == topic_name), None)
    if hop_topic is not None:
        hop_topic_pk = hop_topic['pk']
        logger.debug(f'_get_hop_topic_pk: PK for topic {topic_name} is {hop_topic_pk}')
    else:
        hop_topic_pk = None
        logger.error(f'_get_hop_topic_pk: Can not find topic {topic_name} in Hop Auth topics.')

    return hop_topic_pk


def _get_hop_credential_pk(user, user_hop_auth, user_pk=None, user_api_token=None):
    """Return the PK of the given Hop Auth (user_hop_auth) instance for the user.

    user is vo_person_id
    """
    if user_api_token is None:
        user_api_token = get_user_api_token(user)
    if user_pk is None:
        user_pk = _get_hop_user_pk(user)

    # get the list of credentials for the user
    hop_credentials = get_user_hop_authorizations(user, user_api_token)
    # TODO: rename get_user_hop_authorizations to get_user_hop_credentials

    # extract the one that matches the Auth user.username
    # this is the idiom for searchng a list of dictionaries for certain key-value (topic_name)
    hop_cred = next((item for item in hop_credentials if item['username'] == user_hop_auth.username), None)
    logger.debug(f'_get_hop_credential_pk: hop_cred {hop_cred}')

    if hop_cred is not None:
        hop_cred_pk = hop_cred['pk']
        logger.debug(f'_get_hop_credential_pk: PK for credential {user_hop_auth.username} is {hop_cred_pk}')
    else:
        hop_cred_pk = None
        logger.error(f'_get_hop_credential_pk: Can not find credential {user_hop_auth.username} in Hop Auth credentials.')

    return hop_cred_pk



def get_user_hop_authorization(vo_person_id, user_api_token=None) -> Auth:
    """return the hop.auth.Auth instance for the user with the given vo_person_id
    """
    if user_api_token is None:
        user_api_token = get_user_api_token(vo_person_id)

    # Construct URL to create Hop Auth SCRAM credentials for this user
    hop_user_pk = _get_hop_user_pk(vo_person_id, user_api_token)  # need the pk for the URL
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

# TODO: rename get_user_hop_authorizations to get_user_hop_credentials
def get_user_hop_authorizations(vo_person_id, user_api_token=None):
    """return a list of credential dictionaries for the user with vo_person_id

    The dictionaries look like this:
        {
            'pk': 147,
            'owner': 73,  # this is the PK of the Hop Auth User
            'username': 'llindstrom-2b434c1a',
            'created_at': '2022-03-23T12:42:06.900590-07:00',
            'suspended': False,
            'description': ''
        }
    and we return a list of them.
    """
    if user_api_token is None:
        user_api_token = get_user_api_token(vo_person_id)

    hop_user_pk = _get_hop_user_pk(vo_person_id, user_api_token)  # need the pk for the URL

    # limit the API query to the specific users (whose pk we just found)
    user_credentials_url = get_hop_auth_api_url() + f'/users/{hop_user_pk}/credentials'
    logger.debug(f'HopAuthTestView user_credentials URL: {user_credentials_url}')

    user_credentials_response = requests.get(user_credentials_url,
                                             headers={'Authorization': user_api_token,
                                                      'Content-Type': 'application/json'})
    # from the response, extract the list of user credential dictionaries
    user_hop_authorizations = user_credentials_response.json()
    logger.debug(f'HopAuthTestView get_user_hop_authorizations : {user_hop_authorizations}')
    return user_hop_authorizations

# TODO: rename delete_user_hop_authorizations to delete_user_hop_credentials
def delete_user_hop_authorization(vo_person_id, user_hop_auth: Auth, user_api_token=None):
    """Remove the given SCRAM credentials from Hop Auth

    The intention is for HERMES to create user SCRAM credentials in Hop Auth
    when the user logs in (to HERMES). HERMES will save the hop.auth.Auth instance
    in the Django Session and use it for Alert submission to Hopskotch. Then, when
    the user logs out of HERMES, use this function to delete the SCRAM credentials
    from Hop Auth. (All this should be transparent to the user).
    """
    if user_api_token is None:
        user_api_token = get_user_api_token(vo_person_id)

    hop_user_pk = _get_hop_user_pk(vo_person_id, user_api_token)  # need the pk for the URL

    user_credentials_url = get_hop_auth_api_url() + f'/users/{hop_user_pk}/credentials'
    logger.debug(f'HopAuthTestView user_credentials URL: {user_credentials_url}')

    # find the <PK> of the SCRAM credential just issued
    user_credentials_response = requests.get(user_credentials_url,
                                             headers={'Authorization': user_api_token,
                                                      'Content-Type': 'application/json'})
    # from the response, extract the list of user credential dictionaries
    user_creds = user_credentials_response.json()
    # this is the idiom for searchng a list of dictionaries for certain key-value (username)
    user_cred = next((item for item in user_creds if item["username"] == user_hop_auth.username), None)
    if user_cred is not None:
        scram_pk = user_cred['pk']
        user_credentials_detail_api_suffix = f'/users/{hop_user_pk}/credentials/{scram_pk}'
        user_credentials_detail_url = get_hop_auth_api_url() + user_credentials_detail_api_suffix
        logger.debug(f'HopAuthTestView SCRAM cred: {user_cred}')
        logger.debug(f'HopAuthTestView user_credentials_detail_url: {user_credentials_detail_url}')

        # delete the user SCRAM credential in Hop Auth
        user_credentials_delete_response = requests.delete(user_credentials_detail_url,
                                                           headers={'Authorization': user_api_token,
                                                                    'Content-Type': 'application/json'})
        logger.debug(
            (f'HopAuthTestView user_credentials_delete_response: {responses[user_credentials_delete_response.status_code]}',
             f'[{user_credentials_delete_response.status_code}]'))
    else:
        logger.error(f'HopAuthTestView can not clean up SCRAM credential: {user_hop_auth.username} not found in {user_creds}')


def get_user_api_token(vo_person_id: str, hermes_api_token=None):
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


def get_user_groups(vo_person_id, user_api_token=None):
    """return a list of Hop Auth Groups that the user (vo_person_id) is a member of
    """
    if user_api_token is None:
        user_api_token = get_user_api_token(vo_person_id)

    hop_user_pk = _get_hop_user_pk(vo_person_id, user_api_token)  # need the pk for the URL

    # limit the API query to the specific users (whose pk we just found)
    user_groups_url = get_hop_auth_api_url() + f'/users/{hop_user_pk}/memberships'
    logger.debug(f'HopAuthTestView user_credentials URL: {user_groups_url}')

    user_groups_response = requests.get(user_groups_url,
                                        headers={'Authorization': user_api_token,
                                                 'Content-Type': 'application/json'})
    # from the response, extract the list of user groups
    # {'pk': 97, 'user': 73, 'group': 25, 'status': 'Owner'}
    user_groups = user_groups_response.json()
    logger.info(f'get_user_groups : {user_groups}')

    # examine the groups

    group_names = []
    for group_pk in [ group['group'] for group in user_groups]:
        group_url = get_hop_auth_api_url() + f'/groups/{group_pk}'
        group_response = requests.get(group_url,
                                      headers={'Authorization': user_api_token,
                                               'Content-Type': 'application/json'})
        # for example:
        # {'pk': 25, 'name': 'tomtoolkit', 'description': 'TOM Toolkit Integration testing'}
        # {'pk': 26, 'name': 'hermes', 'description': 'Hermes - Messaging for Multi-messenger astronomy'}
        logger.info(f'get_user_groups group_response: {group_response.json()}')
        group_names.append(group_response.json()['name'])

    return group_names

