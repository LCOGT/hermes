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
  * create_credential_for_user()
  * delete_credential()

Lower level and utility functions:
  * TODO: make function glossary
"""
from http.client import responses
import json
import logging
import os
import requests

from django.conf import settings
from django.core.cache import cache
from django.utils import dateparse, timezone
from django.contrib.auth.models import User

from hop.auth import Auth

from rest_framework import status
from rest_framework.response import Response

import scramp

## # this is a (printf-)debugging utility:
## import sys
## # for current func name, specify 0 or no argument.
## # for name of caller of current func, specify 1.
## # for name of caller of caller of current func, specify 2. etc.
## currentFuncName = lambda n=0: sys._getframe(n + 1).f_code.co_name
## # then, after a function def:
##     logger.debug(f'in {currentFuncName()} called by {currentFuncName(1)}')

logger = logging.getLogger(__name__)
#logger.setLevel(logging.DEBUG)

#  The idea is that SCIMMA_ADMIN_BASE_URL is the only configuration
#  needed in settings.py
#  That's why the Hermes Service Account SCiMMA Auth SCRAM Cred is
#  read from the envirionment here. (It might be confusing that they're
#  not in settings.py

#  from the environment, get the HERMES service account credentials for SCiMMA Auth (scimma-admin).
HERMES_USERNAME = os.getenv('HERMES_USERNAME', None)
HERMES_PASSWORD = os.getenv('HERMES_PASSWORD', None)

 # this API client was written against this version of the API
SCIMMA_AUTH_API_VERSION = 0

def get_hop_auth_api_url(api_version=SCIMMA_AUTH_API_VERSION) -> str:
    """Use the SCIMMA_AUTH_BASE_URL from settings.py and construct the API url from that.
    """
    return settings.SCIMMA_AUTH_BASE_URL + f'/api/v{api_version}'


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


def get_hermes_api_token():
    hermes_api_token = cache.get('hermes_api_token', None)
    if not hermes_api_token:
        logger.debug("Hermes api token doesn't exist in cache, regenerating it now.")
        username = HERMES_USERNAME
        password = HERMES_PASSWORD
        hermes_api_token, hermes_api_token_expiration = _get_hermes_api_token(username, password)
        expiration_date = dateparse.parse_datetime(hermes_api_token_expiration)
        # Subtract a small amount from timeout to ensure credential is available when retrieved
        timeout = (expiration_date - timezone.now()).total_seconds() - 60
        cache.set('hermes_api_token', hermes_api_token, timeout=timeout)
    return hermes_api_token


def _get_hermes_api_token(scram_username, scram_password) -> str:
    """return the Hop Auth API token for the HERMES service account
    """
    hop_auth_api_url = get_hop_auth_api_url()

    # Peform the first round of the SCRAM handshake:
    client = scramp.ScramClient(["SCRAM-SHA-512"], scram_username, scram_password)
    client_first = client.get_client_first()
    logger.debug(f'_get_hermes_api_token: SCRAM client first request: {client_first}')

    scram_resp1 = requests.post(hop_auth_api_url + '/scram/first',
                                json={"client_first": client_first},
                                headers={"Content-Type":"application/json"})
    logger.debug(f'_get_hermes_api_token: SCRAM server first response: {scram_resp1.json()}')

    # Peform the second round of the SCRAM handshake:
    client.set_server_first(scram_resp1.json()["server_first"])
    client_final = client.get_client_final()
    logger.debug(f'_get_hermes_api_token: SCRAM client final request: {client_final}')

    scram_resp2 = requests.post(hop_auth_api_url + '/scram/final',
                                json={"client_final": client_final},
                                headers={"Content-Type":"application/json"})
    logger.debug(f'_get_hermes_api_token: SCRAM server final response: {scram_resp2.json()}')

    client.set_server_final(scram_resp2.json()["server_final"])

    # Get the token we should have been issued:
    response_json = scram_resp2.json()
    hermes_api_token = response_json["token"]
    hermes_api_token_expiration = response_json['token_expires']
    hermes_api_token = f'Token {hermes_api_token}'  # Django wants this (Token<space>) prefix
    logger.debug(f'_get_hermes_api_token: Token issued: {hermes_api_token} expiration: {hermes_api_token_expiration}')

    return hermes_api_token, hermes_api_token_expiration


def get_or_create_user(claims: dict):
    """Create a User instance in the SCiMMA Auth Django project. If a SCiMMA Auth User
    matching the claims already exists, return that Users json dict from the API..

    Because this method requires the OIDC Provider claims, it must be called from some where
    the claims are available, e.g.
     * `auth_backend.HopskotchOIDCAuthenticationBackend.create_user` (if the Hermes User doesn't exist).
     * `auth_backend.HopskotchOIDCAuthenticationBackend.update_user.` (if the Hermes User does exist).

    :param claims: The claims dictionary from the OIDC Provider.
    :type claims: dict

    Hermes requires that SCiMMA Auth have a User instance matching the OIDC claims.
    (Both Hermes and SCiMMA Auth have similar OIDC Provider configuration and workflows).

    The claims dictionary is passed through to the SCiMMA Auth API as the request.data and
    it looks like this:
    {
        'sub': 'edb01519-2541-4fa4-a96b-95d09e152f51',
        'email': 'lindy.lco@gmail.com'
        'email_verified': False,
        'name': 'W L',
        'given_name': 'W',
        'family_name': 'L',
        'preferred_username': 'lindy.lco@gmail.com',
        'upstream_idp': 'http://google.com/accounts/o8/id',
        'is_member_of': ['/Hopskotch Users'],
    }
    However, SCiMMA Auth needs the following keys added:
    {
        'vo_person_id': claims['sub']
    }
    (This is for historical reasons having to do with the CILogon to Keycloak move).

    If a User matching the given claims already exists at SCiMMA Auth,
    return it's JSON dict, which looks like this:
    {
        "pk": 45,
        "username": "0d988bdd-ec83-420d-8ded-dd9091318c24",
        "email": "llindstrom@lco.global"
    }
    """
    logger.debug(f'get_or_create_user claims: {claims}')

    # check to see if the user already exists in SCiMMA Auth
    hermes_api_token = get_hermes_api_token()
    username = claims['sub']

    hop_user = get_hop_user(username, hermes_api_token)
    if hop_user is not None:
        logger.debug(f'get_or_create_user SCiMMA Auth User {username} already exists')
        return hop_user, False  # not created
    else:
        logger.debug(f'hopskotch.get_or_create_user {username}')
        # add the keys that SCiMMA Auth needs
        claims['vo_person_id'] = username

        # pass the claims on to SCiMMA Auth to create the User there.
        url = get_hop_auth_api_url() +  f'/users'
        # this requires admin priviledge so use HERMES service account API token
        response = requests.post(url, json=claims,
                                 headers={'Authorization': hermes_api_token,
                                          'Content-Type': 'application/json'})
        hop_user = json.loads(response.text)

        logger.debug(f'get_or_create_user {responses[response.status_code]} [{response.status_code}]')
        logger.debug(f'get_or_create_user response.text: {response.text} type: {type(response.text)}')
        logger.debug(f'get_or_create_user new hop_user: {hop_user} type: {type(hop_user)}')

        return hop_user, True


def verify_credential_for_user(username: str, user_pk: int, credential_name: str, credential_pk: int):
    """
    """
    url = get_hop_auth_api_url() + f'/users/{user_pk}/credentials/{credential_pk}'
    user_api_token = get_user_api_token(username)

    try:
        response = requests.get(url,
                                headers={'Authorization': user_api_token,
                                        'Content-Type': 'application/json'})
        response.raise_for_status()
        credential = response.json()
        if credential.get('username') == credential_name:
            return True
        else:
            logger.warning(f"Credential with pk {credential_pk} for user {username} does not match credential name {credential_name}")
    except Exception as e:
        logger.warning(f"Failed to verify credential with pk {credential_pk} for user {username}")

    return False


def check_and_regenerate_hop_credential(user: User):
    """ Check that the Django model user profile has a valid credential, and if not, generate a new one
    """
    if ((not user.profile.credential_name or not user.profile.credential_password) or
        not verify_credential_for_user(user.username, user.profile.hop_user_pk,
                                       user.profile.credential_name, user.profile.credential_pk)):
        regenerate_hop_credential(user)


def regenerate_hop_credential(user: User):
    """ Create hop credential for django model user
    """
    hop_auth, user_pk, credential_pk = create_credential_for_user(user.get_username())
    user.profile.hop_user_pk = user_pk
    user.profile.credential_pk = credential_pk
    user.profile.credential_name = hop_auth.username
    user.profile.credential_password = hop_auth.password
    user.profile.save()


def create_credential_for_user(username: str, hermes_api_token: str = None) -> Auth:
    """Set up user for all Hopskotch interactions.
    (Should be called upon logon (probably via OIDC authenticate)

    In SCiMMA Auth:
    * adds User with username to 'hermes' group
    * creates user SCRAM credential (hop.auth.Auth instance)
    * add 'hermes.test' topic permissions to SCRAM credential
    * returns hop.auth.Auth to authenticate() for inclusion in Session dictionary
    """
    logger.info(f'create_credential_for_user Authorizing for Hopskotch, user: {username}')

    if not hermes_api_token:
        hermes_api_token = get_hermes_api_token()

    user_api_token = get_user_api_token(username, hermes_api_token=hermes_api_token)
    hop_user = get_hop_user(username, user_api_token)
    user_pk = hop_user['pk']

    # create user SCRAM credential (hop.auth.Auth instance)
    user_hop_auth: Auth = get_user_hop_authorization(hop_user, user_api_token)
    logger.info(f'create_credential_for_user SCRAM credential created for {username}:  {user_hop_auth.username}')
    credential_pk = _get_hop_credential_pk(username, user_hop_auth.username, user_api_token=user_api_token, user_pk=user_pk)

    add_permissions_to_credential(user_pk, credential_pk, user_api_token=user_api_token, hermes_api_token=hermes_api_token)

    return user_hop_auth, user_pk, credential_pk


def add_permissions_to_credential(user_pk, credential_pk, user_api_token, hermes_api_token):
    """Via SCiMMA Auth API, add a CredentialKafkaPermisson to the given credential_pk for every applicable Topic.

    Applicable Topics is determined by
        For each Group that the User is a member of
            For each permission_received (GroupKafkaPermission)
                The GroupKafkaPermission's 'topic' is an applicable topic for it's 'operation'

    This method determines the applicable Topics ('pk' and 'operation') and hands off the work to
    _add_permission_to_credential_for_user().

    This method also adds the User to the hermes group if not already a Member.
    """
    user_groups = get_user_groups(user_pk, user_api_token)
    user_group_pks = [group['pk'] for group in user_groups]

    # add User to hermes group if not already in the hermes group
    hermes_group_name = 'hermes'
    if not hermes_group_name in [group['name'] for group in user_groups]:
        # must get the hermes_group_pk from ALL the groups, not just the user_groups
        hermes_group_pk = _get_hop_group_pk(hermes_group_name, user_api_token=user_api_token)
        add_user_to_group(user_pk, hermes_group_pk, hermes_api_token)
    else:
        logger.info(f'add_permissions_to_credential User (pk={user_pk}) already a member of group {hermes_group_name}')

    for group_pk in user_group_pks:
        for group_permission in get_group_permissions_received(group_pk, user_api_token):
            logger.info((f'add_permissions_to_credential Adding {group_permission["operation"]} permission to '
                         f'topic {group_permission["topic"]} for user(cred): {user_pk}({credential_pk})'))
            _add_permission_to_credential_for_user(user_pk, credential_pk, group_permission['topic'],
                                                   group_permission['operation'], user_api_token)

def delete_credential(username: str, credential: Auth, user_api_token):
    """Remove from Hop Auth the SCRAM credentials (user_hop_auth) that were created
    for this session.

    This should be called from the OIDC_OP_LOGOUT_URL_METHOD, upon HERMES logout.
    """
    logger.info(f'delete_credential for user: {username} auth: {credential.username}')
    delete_user_hop_credentials(username, credential.username, user_api_token)


def add_user_to_group(user_pk, group_pk, hermes_api_token):
    """Add the User with user_pk to the Group with group_pk as Member.

    Requires Admin privilege, so hermes_api_token is needed.

    Typically used to add User to hermes group.
    """
    url = get_hop_auth_api_url() +  f'/groups/{group_pk}/members'
    request_data = {
        'user':  user_pk,
        'group': group_pk,
        'status': 1,  # Member=1, Owner=2
    }
    # this requires admin priviledge so use HERMES service account API token
    # SCiMMA Auth returns  400 Bad Request if the user is already a member of the group
    response = requests.post(url,
                             json=request_data,
                             headers={'Authorization': hermes_api_token,
                                      'Content-Type': 'application/json'})

    if response.status_code == 400:
        logger.error(f'add_user_to_group ({response.status_code}) request_data: {request_data}')
    elif response.status_code == 201:
        logger.info(f'add_user_to_group ({response.status_code}) User added to Group. request_data: {request_data}')
    else:
        logger.warning(f'add_user_to_group response.status_code: {response.status_code} request_data: {request_data}')
        logger.debug(f'add_user_to_group response.text: {response.text}')


def get_hop_user(username, api_token) -> dict:
    """Return the SCiMMA Auth User with the given username.
    If no SCiMMA Auth User exists with the given username, return None.

    /api/v0/users returns a list of User dictionaries of the form:

    {
        "pk": 20,
        "username": "0d988bdd-ec83-420d-8ded-dd9091318c24",
        "email": "llindstrom@lco.global"
    }
    """
    # TODO: this is illegal -- don't show other people's email addresses GDPR violation
    # request the list of users from the Hop Auth API
    url = get_hop_auth_api_url() + '/users'
    response = requests.get(url,
                            headers={'Authorization': api_token,
                                     'Content-Type': 'application/json'})

    if response.status_code == 200:
        # from the response, extract the list of user dictionaries
        hop_users = response.json()

        # find the user dict whose username matches our username
        # this is the idiom for searchng a list of dictionaries for certain key-value (username)
        hop_user = next((item for item in hop_users if item['username'] == username), None)
        logger.info(f'get_hop_user hop_user: {hop_user}')
    else:
        logger.debug(f'get_hop_user: response.json(): {response.json()}')
        hop_user = None

    if hop_user is None:
        logger.warning(f'get_hop_user: SCiMMA Auth user {username} not found.')

    return hop_user


def _get_hop_user_pk(username, api_token) -> int:
    """Return the primary key of this user from the Hop Auth API. Returns None if
    no user with the given username is returned from the API.
    """
    hop_user = get_hop_user(username, api_token)
    if hop_user is not None:
        hop_user_pk = hop_user['pk']
    else:
         hop_user_pk = None
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
    """Return the Topic dictionary for the Topic with given primary key.

    /api/v0/topics/<PK> returns a topic dictionary of the form:
    {
        'pk': the PK of the topic,
        'owning_group': the PK of the group,
        'name': <str>,
        'publically_readable': Boolean,
        'description': <str>
    }
    """
    url = get_hop_auth_api_url() + f'/topics/{topic_pk}'
    response = requests.get(url,
                            headers={'Authorization': user_api_token,
                                     'Content-Type': 'application/json'})
    topic = response.json()
    return topic


def _get_hop_topic_pk(topic_name, user_api_token) -> int:
    """return the primary key of the given topic from the Hop Auth API
    """
    logger.warning(f'_get_hop_topic_pk: Calling this functions is probably expensive and unnecessary.')

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


def _get_hop_credential_pk(username, credential_name, user_api_token: str, user_pk: int=None):
    """Return the PK of the given SCiMMA Auth credential whose username matches the given
    credential_name.

    NOTES:
      * the username argument is the SCiMMA Auth and HERMES User.get_username()
      * the username key in the returned credential dict is the SCRAM credential name
    """
    if user_pk is None:
        user_pk = _get_hop_user_pk(username, user_api_token)

    # get the list of credentials for the user
    hop_credentials = get_user_hop_credentials(user_pk, user_api_token)

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



def get_user_hop_authorization(hop_user: dict, user_api_token) -> Auth:
    """Return the hop.auth.Auth instance for the user with the given username.
    """
    # extract values from hop_user dict
    hop_user_pk = hop_user['pk']
    username = hop_user['username']

    # Construct URL to create Hop Auth SCRAM credentials for this user
    url = get_hop_auth_api_url() + f'/users/{hop_user_pk}/credentials'

    logger.info(f'get_user_hop_authorization Creating SCRAM credentials for user {username}')
    response = requests.post(url,
                             data=json.dumps({'description': 'Created by HERMES'}),
                             headers={'Authorization': user_api_token,
                                      'Content-Type': 'application/json'})
    # for example, {'username': 'llindstrom-93fee00b', 'password': 'asdlkjfsadkjf'}
    logger.debug(f'get_user_hop_authorization user_credentials_response.json(): {response.json()}')

    # TODO: extract and return credential_pk from response when available (ChrisW working on it)
    user_hop_username = response.json()['username']
    user_hop_password = response.json()['password']

    # you can never again get this SCRAM credential, so save it somewhere (like the Session)
    user_hop_authorization: Auth = Auth(user_hop_username, user_hop_password)

    logger.debug(f'get_user_hop_authorization - new SCRAM creds for {username} username: {user_hop_username} password: {user_hop_password}')

    return user_hop_authorization


def get_user_hop_credentials(user_pk, user_api_token):
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
      * the username key in the returned credential dict is the SCRAM credential name

    """
    # limit the API query to the specific user
    url = get_hop_auth_api_url() + f'/users/{user_pk}/credentials'

    response = requests.get(url,
                            headers={'Authorization': user_api_token,
                                     'Content-Type': 'application/json'})
    # from the response, extract the list of user credential dictionaries
    user_hop_credentials = response.json()
    logger.debug(f'get_user_hop_credentials: {user_hop_credentials}')
    return user_hop_credentials


def delete_user_hop_credential_by_pk(hop_user_pk, credential_pk, user_api_token):
    logger.debug(f'delete_user_hop_credential_by_pk for user pk {hop_user_pk} with credential pk {credential_pk}')
    user_credentials_detail_api_suffix = f'/users/{hop_user_pk}/credentials/{credential_pk}'
    url = get_hop_auth_api_url() + user_credentials_detail_api_suffix

    # delete the user SCRAM credential in Hop Auth
    try:
        response = requests.delete(url,
                                headers={'Authorization': user_api_token,
                                            'Content-Type': 'application/json'})
        logger.debug(
            (f'delete_user_hop_credential_by_pk response: {responses[response.status_code]}',
                f'[{response.status_code}]'))
        response.raise_for_status()
    except Exception as e:
        logger.error(f"delete_user_hop_credential_by_pk - Error deleting credential: {repr(e)}.")


def delete_user_hop_credentials(username, credential_name, user_api_token):
    """Remove the given SCRAM credentials from Hop Auth

    The intention is for HERMES to create user SCRAM credentials in Hop Auth
    when the user logs in (to HERMES). HERMES will save the hop.auth.Auth instance
    in the Django Session and use it for Alert submission to Hopskotch. Then, when
    the user logs out of HERMES, use this function to delete the SCRAM credentials
    from Hop Auth. (All this should be transparent to the user).
    """
    hop_user_pk = _get_hop_user_pk(username, user_api_token)  # need the pk for the URL

    url = get_hop_auth_api_url() + f'/users/{hop_user_pk}/credentials'

    # find the <PK> of the SCRAM credential just issued
    response = requests.get(url,
                            headers={'Authorization': user_api_token,
                                     'Content-Type': 'application/json'})
    # from the response, extract the list of user credential dictionaries
    user_creds = response.json()
    # this is the idiom for searchng a list of dictionaries for certain key-value (username)
    user_cred = next((item for item in user_creds if item["username"] == credential_name), None)
    if user_cred is not None:
        credential_pk = user_cred['pk']
        delete_user_hop_credential_by_pk(hop_user_pk, credential_pk, user_api_token)
    else:
        logger.error(f'delete_user_hop_credentials: Can not clean up SCRAM credential: {credential_name} not found in {user_creds}')


def get_user_api_token(username: str, hermes_api_token=None):
    """return a Hop Auth API token for the given user.

    The tuple returned is the API token, and the expiration date as a string.

    You need an API token to get the user API token and that's what the
    HERMES service account is for. Use the hermes_api_token (the API token
    for the HERMES service account), to get the API token for the user with
    the given username. If the hermes_api_token isn't passed in, get one.
    """
    user_api_token = cache.get(f'user_{username}_api_token', None)
    if not user_api_token:
        logger.debug(f"User {username} api token doesn't exist in cache, regenerating it now.")
        # Set up the URL
        # see scimma-admin/scimma_admin/hopskotch_auth/urls.py (scimma-admin is Hop Auth repo)
        url = get_hop_auth_api_url() + '/oidc/token_for_user'

        # Set up the request data
        # the username comes from the request.user.username for OIDC Provider-created
        # User instances. It is the value of the sub key from Keycloak
        # that Hop Auth (scimma-admin) is looking for.
        # see scimma-admin/scimma_admin.hopskotch_auth.api_views.TokenForOidcUser
        hop_auth_request_data = {
            'vo_person_id': username, # this key didn't change over the switch to Keycloak
        }

        if not hermes_api_token:
            hermes_api_token = get_hermes_api_token()

        # Make the request and extract the user api token from the response
        response = requests.post(url,
                                data=json.dumps(hop_auth_request_data),
                                headers={'Authorization': hermes_api_token,
                                        'Content-Type': 'application/json'})

        if response.status_code == 200:
            # get the user API token out of the response
            token_info = response.json()
            user_api_token = token_info['token']
            user_api_token = f'Token {user_api_token}'  # Django wants a 'Token ' prefix
            user_api_token_expiration_date_as_str = token_info['token_expires']
            # Subtract a small amount from timeout to ensure credential is available when retrieved
            expiration_date = dateparse.parse_datetime(user_api_token_expiration_date_as_str)
            timeout = (expiration_date - timezone.now()).total_seconds() - 60
            cache.set(f'user_{username}_api_token', user_api_token, timeout=timeout)
            logger.debug("Caching ")
            logger.debug(f'get_user_api_token username: {username};  user_api_token: {user_api_token}')
            logger.debug(f'get_user_api_token user_api_token Expires: {user_api_token_expiration_date_as_str}')
        else:
            logger.error((f'get_user_api_token response.status_code: '
                        f'{responses[response.status_code]} [{response.status_code}] ({url})'))

    return user_api_token


def get_user_groups(user_pk: int, user_api_token):
    """Return a list of Hop Auth Groups that the user with user_pk is a member of

    First get the User's Groups with /api/v0/users/<PK>/memberships then
    for each membership, get the Group details with /api/v0/groups/<PK>.

    Returns a list of Group dictionaries of the form:
    {
    "pk": 25,
    "name": "tomtoolkit",
    "description": "TOM Toolkit Integration testing"
    }
    """
    # limit the API query to the specific users (whose pk we just found)
    user_memberships_url = get_hop_auth_api_url() + f'/users/{user_pk}/memberships'

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

    url = get_hop_auth_api_url() +  f'/users/{user_pk}/credentials/{credential_pk}/permissions'
    request_data = {
        'principal':  credential_pk,
        'topic': topic_pk,
        'operation': operation_code,
    }
    # this requires admin priviledge so use HERMES service account API token
    response = requests.post(url,
                             json=request_data,
                             headers={'Authorization': api_token,
                                      'Content-Type': 'application/json'})
    if response.status_code == 500:
        logger.error((f'_add_permission_to_credential_for_user ({response.status_code}) Failed to add {operation} '
                      f'permission to topic {_get_hop_topic_from_pk(topic_pk, api_token)}'))
        logger.debug(f'_add_permission_to_credential_for_user response.text {response.text}')
    elif response.status_code == 200 or response.status_code == 201:
        logger.debug((f'_add_permission_to_credential_for_user ({response.status_code}) Added {operation} '
                      f'permission to {request_data}'))
    else:
        logger.warning((f'_add_permission_to_credential_for_user ({response.status_code}) 201 expected for {operation} '
                        f'permission to {request_data}'))


def get_user_writable_topics(username, hop_user_pk, credential_name, credential_pk, user_api_token, exclude_groups=None):
    logger.warning(f"Get user writable topics with username {username}, credential {credential_name}, token {user_api_token}")
    perm_url = get_hop_auth_api_url() + f'/users/{hop_user_pk}/credentials/{credential_pk}/permissions'
    perm_response = requests.get(perm_url,
                                 headers={'Authorization': user_api_token,
                                          'Content-Type': 'application/json'})
    permissions = perm_response.json()
    topics = []
    for permission in permissions:
        # Check if permission is ALL or Write
        if permission['operation'] in ['All', 'Write']:

            # get the topic name for this this permission
            topic_pk = permission['topic']
            topic = _get_hop_topic_from_pk(topic_pk, user_api_token)
            # topic dictionaries looks like this:
            # {'pk': 397, 'owning_group': 25, 'name': 'tomtoolkit.test', 'publicly_readable': False, 'description': ''}
            topics.append(topic['name'])
    if exclude_groups:
        for group in exclude_groups:
            topics = [topic for topic in topics if not topic.startswith(group)]
    return topics


def get_user_topic_permissions(username, credential_name, user_api_token,
                               exclude_groups=None, include_public_topics=True):
    """Get the Read/Write topic permissions for the given user.

    Returns a dictionary: {
        'read' : [topic_name, ...],
        'write': [topic_name, ...]
    }

    Topics owned by Groups listed in the exclude_groups: list(str) are filtered.

    Adds publicly_readable topics to the 'read': <topic_list>, if include_public_topics is True.
    """
    logger.debug(f'get_user_topic_permissions user: {username} credential: {credential_name}')

    hop_user_pk = _get_hop_user_pk(username, user_api_token)  # need the pk for the URL    
    hop_cred_pk = _get_hop_credential_pk(username, credential_name, user_api_token=user_api_token)
    user_topic_permissions = _get_user_topic_permissions(hop_user_pk, hop_cred_pk, user_api_token)

    if include_public_topics:
        # add the publicly_readable topics to the list of readable topics fro the user
        public_topic_names = [topic['name'] for topic in get_topics(user_api_token, publicly_readable_only=True)]
        user_topic_permissions['read'] = list(set(user_topic_permissions['read'] + public_topic_names))
    if exclude_groups:
        for group in exclude_groups:
            # filter topics owned by groups in the exclude_groups list of group names
            user_topic_permissions['write'] = [topic for topic in user_topic_permissions['write'] if not topic.startswith(group)]
            user_topic_permissions['read'] = [topic for topic in user_topic_permissions['read'] if not topic.startswith(group)]

    return user_topic_permissions


def _get_user_topic_permissions(user_pk, credential_pk, user_api_token):
    """ See doc string for get_user_topic_permissions.
    Use this function when you already have the PKs for the User and Credential.

    /api/v0//users/{user_pk}/credentials/{cred_pk}/permissions returns dictionaries of the form:
    {
        'pk': 811,
        'principal': 147,
        'topic': 398,
        'operation': 'All'
    }

    However, this method returns a dictionary like this:
    {
        'read' : [topic_name, ...],
        'write': [topic_name, ...]
    }
    """
    perm_url = get_hop_auth_api_url() + f'/users/{user_pk}/credentials/{credential_pk}/permissions'
    perm_response = requests.get(perm_url,
                                 headers={'Authorization': user_api_token,
                                          'Content-Type': 'application/json'})
    permissions = perm_response.json()

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

