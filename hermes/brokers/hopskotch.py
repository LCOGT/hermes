"""hermes/brokers/hopskotch.py

Interaction with the HOPSKOTCH Kafka stream and it's associated APIs happen here.

After the SCIMMA_ADMIN_BASE_URL is defined in settings.py, this module encodes specifics
of the scimma_admin (hopauth) API that goes beyond that configuration. That is, this module
is intended depend on HOPSKOTCH/hopauth/scimma_admin specifics. For example, how the versioning
works, etc

Notes on the change of OIDC Provider from CILogon to SCiMMA's Keycloak instance:
 * Usernames
   * for CILogon, 'vo_person_id' was the key of the username claim. It looked like this: SCiMMA10000030
   * for Keycloak, 'sub' is the key of the username claim. Like this: 0d988bdd-ec83-420d-8ded-dd9091318c24
   * In the changeover from CILogon to Keycloak, vo_person_id variable names were changed to username

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
#logger.setLevel(logging.DEBUG)

#  from the environment, get the HERMES service account credentials for SCiMMA pAuth (scimma-admin).
HERMES_USERNAME = os.getenv('HERMES_USERNAME', None)
HERMES_PASSWORD = os.getenv('HERMES_PASSWORD', None)

 # set this (to cache it) in first call to get_hop_auth_api_url and
 # return it in subsequent calls so we don't keep hitting the API
HOP_AUTH_API_URL = None

def get_hop_auth_api_url(api_version=None) -> str:
    """Use the HOP_AUTH_BASE_URL from settings.py and construct the API url from that.
    """
    global HOP_AUTH_API_URL
    if HOP_AUTH_API_URL is not None:
        return HOP_AUTH_API_URL

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
            logger.error(f'Error requesting SCiMMA Auth API Version. Using version {hop_auth_api_version}')

    else:
        hop_auth_api_version = api_version

    hop_auth_api_url = hop_auth_base_url + f'/api/v{hop_auth_api_version}'
    HOP_AUTH_API_URL = hop_auth_api_url  # cache this value for furture calls to this function

    logger.debug(f'get_hop_auth_api_url: hop_auth_api_url: {hop_auth_api_url}')

    return hop_auth_api_url


def get_hermes_hop_authorization() -> Auth:
    """return the hop.auth.Auth instance for the HERMES service account

    The HERMES_USERNAME and HERMES_PASSWORD are module level varialbes. (see above).
    They are environment variables and should enter the environmnet as k8s secrets.
    """
    username = HERMES_USERNAME
    password = HERMES_PASSWORD

    if username is None or password is None:
        error_message = 'Supply HERMES service account credentials: set HERMES_USERNAME and HERMES_PASSWORD environment variables.'
        logger.error(error_message)
        return Response({'message': 'HERMES service account credentials for SCiMMA Auth are not set correctly on the server'},
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


def authorize_user(username: str) -> Auth:
    """Set up user for all Hopskotch interactions.
    (Should be called upon logon (probably via OIDC authenticate)

    In SCiMMA Auth:
    * adds User with username to 'hermes' group
    * creates user SCRAM credential (hop.auth.Auth instance)
    * add 'hermes.test' topic permissions to SCRAM credential
    * returns hop.auth.Auth to authenticate() for inclusion in Session dictionary
    """
    logger.info(f'authorize_user Authorizing for Hopskotch, user: {username}')

    # Only Hop Auth admins can add users to groups and permissions to credentials.
    # So, get the hermes_api_token for Authorization to do those things below.
    hermes_api_token = get_hermes_api_token(HERMES_USERNAME, HERMES_PASSWORD)

    user_api_token = get_user_api_token(username, hermes_api_token=hermes_api_token)
    user_pk = _get_hop_user_pk(username, user_api_token=user_api_token)

    # TODO: this should probably be factored out into it's own function
    # Add the user to the hermes group
    group_name = 'hermes'
    group_pk = _get_hop_group_pk(group_name, user_api_token=user_api_token)

    # if user is already in hermes group, don't add
    user_groups = get_user_groups(username, user_api_token=user_api_token)

    if not group_name in [group['name'] for group in user_groups]:
        # add the user
        group_add_url = get_hop_auth_api_url() +  f'/groups/{group_pk}/members'
        logger.debug(f'authorize_user group_add_url: {group_add_url}')
        group_add_request_data = {
            'user':  user_pk,
            'group': group_pk,
            'status': 1,  # Member=1, Owner=2
        }
        # this requires admin priviledge so use HERMES service account API token
        group_add_response = requests.post(group_add_url,
                                           json=group_add_request_data,
                                           headers={'Authorization': hermes_api_token,
                                                    'Content-Type': 'application/json'})
        logger.debug(f'authorize_user group_add_response.text: {group_add_response.text}')
    else:
        logger.info(f'authorize_user User {username} already a member of group {group_name}')

    # create user SCRAM credential (hop.auth.Auth instance)
    user_hop_auth: Auth = get_user_hop_authorization(username)
    logger.info(f'authorize_user SCRAM credential created for {username}:  {user_hop_auth.username}')
    credential_pk = _get_hop_credential_pk(username, user_hop_auth.username, user_pk=user_pk, user_api_token=user_api_token)

    add_permissions_to_credential(username, user_pk, credential_pk, user_api_token=user_api_token)

    return user_hop_auth


def add_permissions_to_credential(username,  user_pk, credential_pk, user_api_token):
    """Via SCiMMA Auth API, add a CredentialKafkaPermisson to the given credential_pk for every applicable Topic.

    Applicable Topics is determined by
        For each Group that the User is a member of
            For each permission_received (GroupKafkaPermission)
                The GroupKafkaPermission's 'topic' is an applicable topic for it's 'operation'

    This method determines the applicable Topics ('pk' and 'operation') and hands off the work to
    _add_permission_to_credential_for_user().
    """
    user_group_pks = [group['pk'] for group in get_user_groups(username, user_api_token)]

    for group_pk in user_group_pks:
        for group_permission in get_group_permissions_received(group_pk, user_api_token):
            if logger.level == logging.DEBUG:
                topic = _get_hop_topic_from_pk(group_permission['topic'], user_api_token)
                logger.debug(f'add_permissions_to_credential adding topic {topic["name"]} operation: {group_permission["operation"]}')
            _add_permission_to_credential_for_user(user_pk, credential_pk, group_permission['topic'], group_permission['operation'], user_api_token)

    if logger.level == logging.DEBUG:
        logger.debug(f'{_get_user_topic_permissions(user_pk, credential_pk, user_api_token )}')


    ##     for group_permission in get_group_topic_permissions(topic['pk'], user_api_token):
    ##         logger.debug(f'add_permissions_to_credential topic_pk: {topic["pk"]}; group_permission: {group_permission}')
    ##         owning_group_pk = group_permission['principal']
    ##         if owning_group_pk in user_group_pks:
    ##             # then the User is a member of this Group and the User's SCRAM Credential
    ##             # should be given a CredentialKafkaPermisson to this topic
    ##             logger.debug(f'add_permissions_to_credential adding {topic["name"]} Permission to {user_hop_auth.username}')
    ##             _add_permission_to_credential_for_user(user_pk, credential_pk, topic['pk'], user_api_token, read_only=True)

    ## # Add the publicly_readable topics to the new Credential
    ## for topic in get_topics(user_api_token, publicly_readable_only=True):
    ##     logger.debug(f'authorize_user adding (Public) {topic["name"]} Permission to {user_hop_auth.username}')
    ##     _add_permission_to_credential_for_user(user_pk, credential_pk, topic['pk'], user_api_token, read_only=True)

    ## # Add all applicable topic permissions to the new Credential
    ## #   Get the Topics owned by each Group that the User belongs to and add them
    ## for group_name in get_user_groups(username, user_api_token=user_api_token):
    ##     # get the topics owned by this group
    ##     for topic in get_group_topics(group_name, user_api_token):
    ##         if topic['publicly_readable']:
    ##             continue  # we've already added this topic
    ##         logger.debug(f'authorize_user adding ({group_name}) {topic["name"]} Permission to {user_hop_auth.username}')
    ##         _add_permission_to_credential_for_user(user_pk, credential_pk, topic['pk'], user_api_token)

    # TODO: when it is a function, use it to add the user to the gcn.circular group for Read access
#    topic_name = 'hermes.test'
#    topic_pk = _get_hop_topic_pk(topic_name, user_api_token)
#    # add hermes.test topic permissions to the new SCRAM credential
#    credential_permission_url = get_hop_auth_api_url() +  f'/users/{user_pk}/credentials/{credential_pk}/permissions'
#    credential_permission_request_data = {
#        'principal':  credential_pk,
#        'topic': topic_pk,
#        'operation': 1,  # All=1, Read=2, Write=3, etc, etc
#    }
#    # this requires admin priviledge so use HERMES service account API token
#    credential_permission_response = requests.post(credential_permission_url,
#                                                   json=credential_permission_request_data,
#                                                   headers={'Authorization': hermes_api_token,
#                                                            'Content-Type': 'application/json'})
#    logger.debug(f'authorize_user credential_permission_response.text:   {credential_permission_response.text}')


def deauthorize_user(username: str, user_hop_auth: Auth):
    """Remove from Hop Auth the SCRAM credentials (user_hop_auth) that were created
    for this session.

    This should be called from the OIDC_OP_LOGOUT_URL_METHOD, upon HERMES logout.
    """
    logger.info(f'deauthorize_user Deauthorizing for Hopskotch, user: {username} auth: {user_hop_auth.username}')
    delete_user_hop_credentials(username, user_hop_auth.username)


def _get_hop_user_pk(username, user_api_token) -> int:
    """return the primary key of this user from the Hop Auth API

    username-ss are assigned by Keycloak and are of the form: <see module doc string>.
    The api/v0/users API endpoint returns a list of user dictionaries with
    keys of (pk, username, email), where the username is the username
    """
    # request the list of users from the Hop Auth API
    users_url = get_hop_auth_api_url() + '/users'
    response = requests.get(users_url,
                            headers={'Authorization': user_api_token,
                                     'Content-Type': 'application/json'})
    # from the response, extract the list of user dictionaries
    hop_users = response.json()
    # find the user dict whose username matches our username
    # this is the idiom for searchng a list of dictionaries for certain key-value (username)
    hop_user = next((item for item in hop_users if item['username'] == username), None)
    if hop_user is not None:
        hop_user_pk = hop_user['pk']
        logger.debug(f'_get_hop_user_pk: PK for {username} is {hop_user_pk}')
    else:
        hop_user_pk = None
        logger.error(f'_get_hop_user_pk: Can not find user {username} in Hop Auth users.')

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


def _get_hop_topic_from_pk(topic_pk, user_api_token) -> str:
    topic_url = get_hop_auth_api_url() + f'/topics/{topic_pk}'
    response = requests.get(topic_url,
                            headers={'Authorization': user_api_token,
                                     'Content-Type': 'application/json'})
    # example topic dictionary:
    # {'pk': 84, 'owning_group': 10, 'name': 'lvalert-dev.external_snews',
    #  'publicly_readable': False, 'description': ''}
    hop_topic = response.json()
    return hop_topic


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


def _get_hop_credential_pk(username, credential_name, user_pk=None, user_api_token=None):
    """Return the PK of the given SCiMMA Auth credential whose username matches the given
    credential_name.

    NOTES:
      * the username argument is the SCiMMA Auth and HERMES User.get_username()
      * the username key in the returned credential dict is the SCRAM credential name
    """
    if user_api_token is None:
        user_api_token = get_user_api_token(username)
    if user_pk is None:
        user_pk = _get_hop_user_pk(username, user_api_token)

    # get the list of credentials for the user
    hop_credentials = get_user_hop_credentials(username, user_api_token)

    # extract the one that matches the Auth user.username
    # this is the idiom for searchng a list of dictionaries for certain key-value (topic_name)
    hop_cred = next((item for item in hop_credentials if item['username'] == credential_name), None)
    logger.debug(f'_get_hop_credential_pk: hop_cred {hop_cred}')

    if hop_cred is not None:
        hop_cred_pk = hop_cred['pk']
        logger.debug(f'_get_hop_credential_pk: PK for credential {credential_name} is {hop_cred_pk}')
    else:
        hop_cred_pk = None
        logger.error(f'_get_hop_credential_pk: Can not find credential {credential_name} in Hop Auth credentials.')

    return hop_cred_pk



def get_user_hop_authorization(username, user_api_token=None) -> Auth:
    """Return the hop.auth.Auth instance for the user with the given username.
    """
    if user_api_token is None:
        user_api_token = get_user_api_token(username)

    # Construct URL to create Hop Auth SCRAM credentials for this user
    hop_user_pk = _get_hop_user_pk(username, user_api_token)  # need the pk for the URL
    user_credentials_url = get_hop_auth_api_url() + f'/users/{hop_user_pk}/credentials'

    logger.info(f'get_user_hop_authorization Creating SCRAM credentials for user {username}')
    user_credentials_response = requests.post(user_credentials_url,
                                              data=json.dumps({'description': 'Created by HERMES'}),
                                              headers={'Authorization': user_api_token,
                                                       'Content-Type': 'application/json'})
    logger.debug(f'HopAuthTestView user_credentials_response.json(): {user_credentials_response.json()}')

    user_hop_username = user_credentials_response.json()['username']
    user_hop_password = user_credentials_response.json()['password']

    # you can never again get this SCRAM credential, so save it somewhere (like the Session)
    user_hop_authorization: Auth = Auth(user_hop_username, user_hop_password)

    logger.debug(f'get_user_hop_authorization - new SCRAM creds for {username} username: {user_hop_username} password: {user_hop_password}')

    return user_hop_authorization


def get_user_hop_credentials(username, user_api_token=None):
    """return a list of credential dictionaries for the user with the given username

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

    NOTES:
      * the username argument is the SCiMMA Auth and HERMES User.get_username()
      * the username key in the returned credential dict is the SCRAM credential name

    """
    if user_api_token is None:
        user_api_token = get_user_api_token(username)

    hop_user_pk = _get_hop_user_pk(username, user_api_token)  # need the pk for the URL

    # limit the API query to the specific users (whose pk we just found)
    user_credentials_url = get_hop_auth_api_url() + f'/users/{hop_user_pk}/credentials'

    user_credentials_response = requests.get(user_credentials_url,
                                             headers={'Authorization': user_api_token,
                                                      'Content-Type': 'application/json'})
    # from the response, extract the list of user credential dictionaries
    user_hop_credentials = user_credentials_response.json()
    logger.debug(f'HopAuthTestView get_user_hop_credentials : {user_hop_credentials}')
    return user_hop_credentials


def delete_user_hop_credentials(username, credential_name, user_api_token=None):
    """Remove the given SCRAM credentials from Hop Auth

    The intention is for HERMES to create user SCRAM credentials in Hop Auth
    when the user logs in (to HERMES). HERMES will save the hop.auth.Auth instance
    in the Django Session and use it for Alert submission to Hopskotch. Then, when
    the user logs out of HERMES, use this function to delete the SCRAM credentials
    from Hop Auth. (All this should be transparent to the user).
    """
    if user_api_token is None:
        user_api_token = get_user_api_token(username)

    hop_user_pk = _get_hop_user_pk(username, user_api_token)  # need the pk for the URL

    user_credentials_url = get_hop_auth_api_url() + f'/users/{hop_user_pk}/credentials'

    # find the <PK> of the SCRAM credential just issued
    user_credentials_response = requests.get(user_credentials_url,
                                             headers={'Authorization': user_api_token,
                                                      'Content-Type': 'application/json'})
    # from the response, extract the list of user credential dictionaries
    user_creds = user_credentials_response.json()
    # this is the idiom for searchng a list of dictionaries for certain key-value (username)
    user_cred = next((item for item in user_creds if item["username"] == credential_name), None)
    if user_cred is not None:
        scram_pk = user_cred['pk']
        user_credentials_detail_api_suffix = f'/users/{hop_user_pk}/credentials/{scram_pk}'
        user_credentials_detail_url = get_hop_auth_api_url() + user_credentials_detail_api_suffix
        logger.debug(f'HopAuthTestView SCRAM cred: {user_cred}')

        # delete the user SCRAM credential in Hop Auth
        user_credentials_delete_response = requests.delete(user_credentials_detail_url,
                                                           headers={'Authorization': user_api_token,
                                                                    'Content-Type': 'application/json'})
        logger.debug(
            (f'HopAuthTestView user_credentials_delete_response: {responses[user_credentials_delete_response.status_code]}',
             f'[{user_credentials_delete_response.status_code}]'))
    else:
        logger.error(f'HopAuthTestView can not clean up SCRAM credential: {credential_name} not found in {user_creds}')


def get_user_api_token(username: str, hermes_api_token=None):
    """return a Hop Auth API token for the given user.
    
    You need an API token to get the user API token and that's what the
    HERMES service account is for. Use the hermes_api_token (the API token
    for the HERMES service account), to get the API token for the user with
    the given username. If the hermes_api_token isn't passed in, get one.
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
    # the username comes from the request.user.username for OIDC Provider-created
    # User instances. It is the value of the sub key from Keycloak
    # that Hop Auth (scimma-admin) is looking for.
    # see scimma-admin/scimma_admin.hopskotch_auth.api_views.TokenForOidcUser
    hop_auth_request_data = {
        'vo_person_id': username, # this key didn't change over the switch to Keycloak
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

        logger.debug(f'get_user_api_token username: {username};  user_api_token: {user_api_token}')
        logger.debug(f'get_user_api_token user_api_token Expires: {user_api_token_expiration_date_as_str}')
    else:
        logger.error((f'HopAuthTestView hopskotch_auth_response.status_code: '
                      f'{responses[response.status_code]} [{response.status_code}]'))
        user_api_token = None # this is a problem

    return user_api_token


def get_user_groups(username, user_api_token=None):
    """Return a list of Hop Auth Groups that the user with username is a member of

    First get the User's Groups with /api/v0/users/<PK>/memberships then
    for each membership, get the Group details with /api/v0/groups/<PK>.

    Returns a list of Group dictionaries of the form:
    {
    "pk": 25,
    "name": "tomtoolkit",
    "description": "TOM Toolkit Integration testing"
    }
    """
    if user_api_token is None:
        user_api_token = get_user_api_token(username)

    hop_user_pk = _get_hop_user_pk(username, user_api_token)  # need the pk for the URL

    # limit the API query to the specific users (whose pk we just found)
    user_memberships_url = get_hop_auth_api_url() + f'/users/{hop_user_pk}/memberships'

    user_memberships_response = requests.get(user_memberships_url,
                                        headers={'Authorization': user_api_token,
                                                 'Content-Type': 'application/json'})
    # from the response, extract the list of user groups
    # GroupMembership: {'pk': 97, 'user': 73, 'group': 25, 'status': 'Owner'}
    user_memberships = user_memberships_response.json()
    logger.debug(f'get_user_groups user_memberships: {user_memberships}')

    # extract the name of the group from the group dictionaries; collect and return the list
    groups = []
    for group_pk in [ group['group'] for group in user_memberships]:
        group_url = get_hop_auth_api_url() + f'/groups/{group_pk}'
        group_response = requests.get(group_url,
                                      headers={'Authorization': user_api_token,
                                               'Content-Type': 'application/json'})
        # for example:
        # {'pk': 25, 'name': 'tomtoolkit', 'description': 'TOM Toolkit Integration testing'}
        # {'pk': 26, 'name': 'hermes', 'description': 'Hermes - Messaging for Multi-messenger astronomy'}
        logger.debug(f'get_user_groups group_response: {group_response.json()}')
        groups.append(group_response.json()) # construct list of Group dictionaries

    return groups


def get_group_topics(group_name, user_api_token) -> list:
    """Return a list of dictionaries describing the topics owned by the given group.

    /api/v0/groups/<PK>/topics returns a list of topic dictionaries of the form:
    {
        'pk': the PK of the topic,
        'owning_group': the PK of the group,
        'name': <str>,
        'publically_readable': Boolean,
        'description': <str>
    }
    """
    group_pk = _get_hop_group_pk(group_name, user_api_token)

    url = get_hop_auth_api_url() + f'/groups/{group_pk}/topics'
    response =  requests.get(url,
                             headers={'Authorization': user_api_token,
                                      'Content-Type': 'application/json'})
    topics = response.json()

    logger.debug(f'get_group_topics for group {group_name} topics: {topics}')
    return topics


def get_topics(user_api_token, publicly_readable_only=False) -> list:
    """Return a list of dictionaries describing SCiMMA Auth Topics.

    By default, get all the topics. Set publicly_readable=True to return only pulicly
    readable topics.

    /api/v0/topics returns a list of topic dictionaries of the form:

    {
        'pk': the PK of the topic,
        'owning_group': the PK of the group,
        'name': <str>,
        'publicly_readable': Boolean,
        'description': <str>
    }
    """
    url = get_hop_auth_api_url() + f'/topics'
    response =  requests.get(url,
                             headers={'Authorization': user_api_token,
                                      'Content-Type': 'application/json'})
    if publicly_readable_only:
        topics = [topic for topic in response.json() if topic['publicly_readable']]
    else:
        topics = response.json()

    return topics


def get_group_permissions_received(group_pk, user_api_token):
    """Return a list of dictionaries describing GroupKafkaPermissions received by the Group.

    /api/v0/groups/<PK>/permissions_received returns a list of GroupKafkaPermission
    dictionaries of the form:

    {
        'pk': the PK of the GroupKafkaPermission,
        'principal': the PK of the Group,
        'topic': the PK of the Topic
        'operation': <str>  # 'All', 'Read', or 'Write'
    }
    """
    url = get_hop_auth_api_url() + f'/groups/{group_pk}/permissions_received'
    logger.debug(f'get_group_permissions_recieved url: {url}')
    response =  requests.get(url,
                             headers={'Authorization': user_api_token,
                                      'Content-Type': 'application/json'})

    logger.debug(f'get_group_permissions_recieved response.status_code: {response.status_code}')
    logger.debug(f'get_group_permissions_recieved response.text: {response.text}')
    permissions = response.json()

    return permissions


def get_group_topic_permissions(topic_pk, user_api_token) -> list:
    """Return a list of dictionaries describing GroupKafkaPermissions for the given Topic.

    /api/v0/topics/<PK>/permissions returns a list of GroupKafkaPermission
    dictionaries of the form:

    {
        'pk': the PK of the GroupKafkaPermission,
        'principal': the PK of the Group,
        'topic': the PK of the Topic
        'operation': <str>  # 'All', 'Read', or 'Write'
    }
    """
    url = get_hop_auth_api_url() + f'/topics/{topic_pk}/permissions'
    response =  requests.get(url,
                             headers={'Authorization': user_api_token,
                                      'Content-Type': 'application/json'})
    permissions = response.json()

    return permissions


def _add_permission_to_credential_for_user(user_pk: int, credential_pk: int, topic_pk: int, operation: str, api_token):
    """Add Permission for the given Topic, to the given Credential of the given User.

    POST to /api/v0/users/<PK>/credentials/<PK>/permissions with POST data:
    data = {
        'principal': <Credential PK>,
        'topic': <Topic PK>,
        'operation': <int> # (1=ALL, 2=READ, 3=WRITE)
    }
    """
    if operation == 'All':
        operation_code = 1
    elif operation == 'Write':
        operation_code = 3
    else:
        operation_code = 2 # Read is least permissive

    credential_permission_url = get_hop_auth_api_url() +  f'/users/{user_pk}/credentials/{credential_pk}/permissions'
    credential_permission_request_data = {
        'principal':  credential_pk,
        'topic': topic_pk,
        'operation': operation_code,
    }
    # this requires admin priviledge so use HERMES service account API token
    credential_permission_response = requests.post(credential_permission_url,
                                                   json=credential_permission_request_data,
                                                   headers={'Authorization': api_token,
                                                            'Content-Type': 'application/json'})
    logger.debug(f'_add_permission_to_credential credential_permission_response.text:   {credential_permission_response.text}')



def get_user_topic_permissions(username, credential_name, user_api_token=None):
    """Returns a dictionary: {
        'read' : [topic_name, ...],
        'write': [topic_name, ...]
    }
    """
    logger.debug(f'get_user_topic_permissions user: {username} credential: {credential_name}')

    if user_api_token is None:
        user_api_token = get_user_api_token(username)

    hop_user_pk = _get_hop_user_pk(username, user_api_token)  # need the pk for the URL    
    hop_cred_pk = _get_hop_credential_pk(username, credential_name, user_api_token=user_api_token)

    perm_url = get_hop_auth_api_url() + f'/users/{hop_user_pk}/credentials/{hop_cred_pk}/permissions'
    perm_response = requests.get(perm_url,
                                 headers={'Authorization': user_api_token,
                                          'Content-Type': 'application/json'})
    permissions = perm_response.json()
    logger.debug(f'get_user_topic_permissions permissions for {credential_name} ({username}): {permissions}')
    # permission dictionaries look like this:
    #     {'pk': 811, 'principal': 147, 'topic': 398, 'operation': 'All'}

    read_topics = []
    write_topics = []
    for permission in permissions:
        # get the topic name for this this permission
        topic_pk = permission['topic']
        topic = _get_hop_topic_from_pk(topic_pk, user_api_token)
        # topic dictionaries looks like this:
        # {'pk': 397, 'owning_group': 25, 'name': 'tomtoolkit.test', 'publicly_readable': False, 'description': ''}
        logger.debug(f'get_user_topic_permissions permission: {permission}')
        logger.debug(f'get_user_topic_permissions      topic: {topic}')

        # In the UI, if Read is checked (only), then permission['operation'] is 'Read'
        # In the UI, if Write is checked (only), then permission['operation'] is 'Write'
        # In the UI, if Read and Write is checked, then permission['operation'] is 'All'

        if permission['operation'] == 'All':
            read_topics.append(topic['name'])
            write_topics.append(topic['name'])
        elif permission['operation'] == 'Write':
            write_topics.append(topic['name'])
        elif permission['operation'] == 'Read':
            read_topics.append(topic['name'])

    #sample_topics = {
    #    'read': ['hermes.test', 'gcn.circular'],
    #    'write': ['hermes.test'],
    #    'notes': 'This is sample data',
    #}

    topic_permissions = {
        'read': read_topics,
        'write': write_topics,
    }

    return topic_permissions

