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
HERMES_USERNAME = settings.SCIMMA_AUTH_USERNAME
HERMES_PASSWORD = settings.SCIMMA_AUTH_PASSWORD


 # this API client was written against this version of the API
SCIMMA_AUTH_API_VERSION = 1

def get_hop_auth_api_url(api_version=SCIMMA_AUTH_API_VERSION) -> str:
    """Use the SCIMMA_AUTH_BASE_URL from settings.py and construct the API url from that.
    """
    return settings.SCIMMA_AUTH_BASE_URL + f'/api/v{api_version}'


def get_hermes_hop_authorization() -> Auth:
    """return the hop.auth.Auth instance for the HERMES service account

    The HERMES_USERNAME and HERMES_PASSWORD are module level varialbes. (see above).
    They are environment variables and should enter the environmnet as k8s secrets.
    """
    if (not HERMES_USERNAME or not HERMES_PASSWORD):
        error_message = 'Supply HERMES service account credentials: set SCIMMA_AUTH_USERNAME and SCIMMA_AUTH_PASSWORD environment variables.'
        logger.error(error_message)
        return Response({'message': 'HERMES service account credentials for SCiMMA Auth are not set correctly on the server'},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    hop_auth: Auth = Auth(HERMES_USERNAME, HERMES_PASSWORD)
    return hop_auth


def get_hermes_api_token():
    hermes_api_token = cache.get('hermes_api_token', None)
    if not hermes_api_token:
        logger.debug("Hermes api token doesn't exist in cache, regenerating it now.")
        hermes_api_token, hermes_api_token_expiration = _get_hermes_api_token(HERMES_USERNAME, HERMES_PASSWORD)
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
        if response.status_code == 201:
            hop_user = response.json()
            logger.debug(f'get_or_create_user new hop_user: {hop_user} type: {type(hop_user)}')
        else:
            logger.debug(f'get_or_create_user failed with status {response.status_code} and content {response.text}')

        return hop_user, True


def verify_credential_for_user(username: str, credential_name: str):
    """
        Attempt to retrieve an existing credential to verify that it exists on the server
    """
    url = get_hop_auth_api_url() + f'/users/{username}/credentials/{credential_name}'
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
            logger.warning(f"Credential with name {credential_name} for user {username} does not match")
    except Exception as e:
        logger.warning(f"Failed to verify credential with name {credential_name} for user {username}: {repr(e)}")

    return False


def check_and_regenerate_hop_credential(user: User):
    """ Check that the Django model user profile has a valid credential, and if not, generate a new one
    """
    if ((not user.profile.credential_name or not user.profile.credential_password) or
        not verify_credential_for_user(user.username, user.profile.credential_name)):
        regenerate_hop_credential(user)


def regenerate_hop_credential(user: User):
    """ Create hop credential for django model user
    """
    hop_auth = create_credential_for_user(user.get_username())
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

    # create user SCRAM credential (hop.auth.Auth instance)
    user_hop_auth = _create_credential_for_user(username, user_api_token)
    logger.info(f'create_credential_for_user SCRAM credential {user_hop_auth.username} created for {username}')

    add_permissions_to_credential(username, user_hop_auth.username, user_api_token=user_api_token, hermes_api_token=hermes_api_token)

    return user_hop_auth


def add_permissions_to_credential(username, credential_name, user_api_token, hermes_api_token):
    """Via SCiMMA Auth API, add a CredentialKafkaPermisson to the given credential_name for every applicable Topic.

    Applicable Topics is determined by
        For each Group that the User is a member of
            For each permission_received (GroupKafkaPermission)
                The GroupKafkaPermission's 'topic' is an applicable topic for it's 'operation'

    This method determines the applicable Topics ('name' and 'operation') and hands off the work to
    _add_permission_to_credential_for_user().

    This method also adds the User to the hermes group if not already a Member.
    """
    user_groups = get_user_groups(username, user_api_token)
    user_group_names = [group['group'] for group in user_groups]

    # add User to hermes group if not already in the hermes group
    hermes_group_name = 'hermes'
    if not hermes_group_name in [group['group'] for group in user_groups]:
        add_user_to_group(username, hermes_group_name, hermes_api_token)
        user_group_names.append(hermes_group_name)
    else:
        logger.info(f'add_permissions_to_credential User (username={username}) already a member of group {hermes_group_name}')

    for group_name in user_group_names:
        for group_permission in get_group_permissions_received(group_name, user_api_token):
            logger.info((f'add_permissions_to_credential Adding {group_permission["operation"]} permission to '
                         f'topic {group_permission["topic"]} for user(cred): {username}({credential_name})'))
            _add_permission_to_credential_for_user(username, credential_name, group_permission['topic'],
                                                   group_permission['operation'], user_api_token)

def delete_credential(username: str, credential: Auth, user_api_token):
    """Remove from Hop Auth the SCRAM credentials (user_hop_auth) that were created
    for this session.

    This should be called from the OIDC_OP_LOGOUT_URL_METHOD, upon HERMES logout.
    """
    logger.info(f'delete_credential for user: {username} auth: {credential.username}')
    delete_user_hop_credentials(username, credential.username, user_api_token)


def add_user_to_group(username, groupname, hermes_api_token):
    """Add the User with username to the Group with groupname as Member.

    Requires Admin privilege, so hermes_api_token is needed.

    Typically used to add User to hermes group.
    """
    url = get_hop_auth_api_url() +  f'/groups/{groupname}/members'
    request_data = {
        'user':  username,
        'group': groupname,
        'status': "Member",
    }
    # this requires admin priviledge so use HERMES service account API token
    # SCiMMA Auth returns  400 Bad Request if the user is already a member of the group
    response = requests.post(url,
                             json=request_data,
                             headers={'Authorization': hermes_api_token,
                                      'Content-Type': 'application/json'})

    if response.status_code == 201:
        logger.info(f'add_user_to_group ({response.status_code}) User added to Group. request_data: {request_data}')
    else:
        logger.warning(f'add_user_to_group response.status_code: {response.status_code} request_data: {request_data}')
        logger.debug(f'add_user_to_group response.text: {response.text}')


def get_hop_user(username, api_token) -> dict:
    """Return the SCiMMA Auth User with the given username.
    If no SCiMMA Auth User exists with the given username, return None.

    /api/v1/users/{username} returns that user dictionary of the form:

    {
        "id": 20,
        "username": "0d988bdd-ec83-420d-8ded-dd9091318c24",
        "email": "llindstrom@lco.global"
    }
    """
    url = f"{get_hop_auth_api_url()}/users/{username}"
    response = requests.get(url,
                            headers={'Authorization': api_token,
                                     'Content-Type': 'application/json'})

    if response.status_code == 200:
        # from the response, extract the user dictionarie
        hop_user = response.json()
        logger.info(f'get_hop_user hop_user: {hop_user}')
    else:
        logger.debug(f'get_hop_user: failed with status {response.status_code} and response.json(): {response.json()}')
        hop_user = None

    if hop_user is None:
        logger.warning(f'get_hop_user: SCiMMA Auth user {username} not found.')

    return hop_user


def _create_credential_for_user(username: str, user_api_token) -> Auth:
    """Creates and returns a new credential's hop Auth for the user with the given username.
    """
    # Construct URL to create Hop Auth SCRAM credentials for this user
    url = get_hop_auth_api_url() + f'/users/{username}/credentials'

    logger.info(f'_create_credential_for_user Creating SCRAM credentials for user {username}')
    user_hop_authorization = None
    try:
        response = requests.post(url,
                                data=json.dumps({'description': 'Created by HERMES'}),
                                headers={'Authorization': user_api_token,
                                        'Content-Type': 'application/json'})
        # for example, {'username': 'llindstrom-93fee00b', 'password': 'asdlkjfsadkjf', 'pk': 0}
        user_hop_username = response.json()['username']
        user_hop_password = response.json()['password']

        # you can never again get this SCRAM credential, so save it somewhere (like the Session)
        user_hop_authorization: Auth = Auth(user_hop_username, user_hop_password)
        logger.debug(f'_create_credential_for_user user_credentials_response.json(): {response.json()}')
    except Exception:
        logger.error(f"_create_credential_for_user Failed to create credential for user {username} with status {response.status_code}: {response.text}")

    return user_hop_authorization


def delete_user_hop_credentials(username, credential_name, user_api_token):
    """Remove the given SCRAM credentials from Hop Auth

    The intention is for HERMES to create user SCRAM credentials in Hop Auth
    when the user logs in (to HERMES). HERMES will save the hop.auth.Auth instance
    in the Django Session and use it for Alert submission to Hopskotch. Then, when
    the user logs out of HERMES, use this function to delete the SCRAM credentials
    from Hop Auth. (All this should be transparent to the user).
    """
    url = get_hop_auth_api_url() + f'/users/{username}/credentials/{credential_name}'

    # find the <PK> of the SCRAM credential just issued
    response = requests.delete(url,
                               headers={'Authorization': user_api_token,
                                        'Content-Type': 'application/json'})
    if response.status_code == 204:
        logger.info(f"delete_user_hop_credentials: Successfully deleted credential {credential_name} for user {username}")
    else:
        logger.error(f'delete_user_hop_credentials: Failed to delete {credential_name} for user {username}: status {response.status_code} and content {response.text}')


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


def get_user_groups(username: str, user_api_token):
    """Return a list of Hop Auth Groups that the user with username is a member of

    Get the User's Groups with /api/v1/users/<username>/memberships.

    Returns a list of Group dictionaries of the form:
    {
    "id": 25,
    "user": "steve",
    "group": "tomtoolkit",
    "status": "Member"
    }
    """
    # limit the API query to the specific users (whose pk we just found)
    user_memberships_url = get_hop_auth_api_url() + f'/users/{username}/memberships'
    user_memberships = []
    try:
        user_memberships_response = requests.get(user_memberships_url,
                                                headers={'Authorization': user_api_token,
                                                        'Content-Type': 'application/json'})
        user_memberships_response.raise_for_status()
        # from the response, extract the list of user groups
        # GroupMembership: {'id': 97, 'user': 'steve', 'group': 'hermes', 'status': 'Owner'}
        user_memberships = user_memberships_response.json()
        logger.debug(f'get_user_groups user_memberships: {user_memberships}')
    except Exception:
        logger.error(f"get_user_groups: Failed to get user groups with status {user_memberships_response.status}: {user_memberships_response.text}")

    return user_memberships


def get_group_permissions_received(group_name, user_api_token):
    """Return a list of dictionaries describing GroupKafkaPermissions received by the Group.

    /api/v1/groups/<group_name>/permissions_received returns a list of GroupKafkaPermission
    dictionaries of the form:

    {
        'id': the id of the GroupKafkaPermission,
        'principal': the group name of the Group,
        'topic': the topic name of the Topic
        'operation': <str>  # 'All', 'Read', or 'Write'
    }
    """
    url = get_hop_auth_api_url() + f'/groups/{group_name}/permissions_received'
    permissions = []
    try:
        response =  requests.get(url,
                                headers={'Authorization': user_api_token,
                                        'Content-Type': 'application/json'})

        logger.debug(f'get_group_permissions_recieved response.status_code: {response.status_code}')
        logger.debug(f'get_group_permissions_recieved response.text: {response.text}')
        response.raise_for_status()
        permissions = response.json()
    except Exception:
        logger.error(f"get_group_permissions_recieved Failed to retrieve group {group_name} permissions with status {response.status_code}: {response.text}")

    return permissions


def _add_permission_to_credential_for_user(username: str, credential_name: str, topic_name: str, operation: str, api_token):
    """Add Permission for the given Topic, to the given Credential of the given User.

    POST to /api/v1/users/<username>/credentials/<credential_name>/permissions with POST data:
    data = {
        'principal': <Credential name>,
        'topic': <Topic name>,
        'operation': <"ALL", "READ", "WRITE">
    }
    """
    url = get_hop_auth_api_url() +  f'/users/{username}/credentials/{credential_name}/permissions'
    request_data = {
        'principal':  credential_name,
        'topic': topic_name,
        'operation': operation,
    }
    try:
        response = requests.post(url,
                                json=request_data,
                                headers={'Authorization': api_token,
                                        'Content-Type': 'application/json'})
        response.raise_for_status()
        logger.debug((f'_add_permission_to_credential_for_user ({response.status_code}) Added '
                      f'permission {request_data} to credential {credential_name} for user {username}'))
    except Exception:
        logger.error((f'_add_permission_to_credential_for_user: Failed to add {operation} '
                      f'permission to topic {topic_name}: status {response.status_code}, response {response.text}'))


def get_user_writable_topics(username, credential_name, user_api_token, exclude_groups=None):
    logger.info(f"Get user writable topics with username {username}, credential {credential_name}, token {user_api_token}")
    perm_url = get_hop_auth_api_url() + f'/users/{username}/credentials/{credential_name}/permissions'
    topics = []
    try:
        perm_response = requests.get(perm_url,
                                    headers={'Authorization': user_api_token,
                                            'Content-Type': 'application/json'})
        perm_response.raise_for_status()
        permissions = perm_response.json()
        for permission in permissions:
            # Check if permission is ALL or Write
            if permission['operation'] in ['All', 'Write']:
                topic = permission['topic']
                topics.append(topic)
        if exclude_groups:
            for group in exclude_groups:
                topics = [topic for topic in topics if not topic.startswith(group)]
    except Exception:
        logger.error(f"get_user_writable_topics: Failed to get writable topics for user {username} on credential {credential_name} with status {perm_response.status_code}: {perm_response.text}")
    return topics
