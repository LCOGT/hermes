"""hermes/brokers/hopskotch.py

Interaction with the HOPSKOTCH Kafka stream and it's associated APIs happen here.
"""
import os

#  from the environment, get the HERMES service account credentials for HopAuth (scimma-admin).
HOP_USERNAME = os.getenv('HOP_USERNAME', 'set the HOP_USENAME')
HOP_PASSWORD = os.getenv('HOP_PASSWORD', 'set the HOP_PASSWORD')
def get_hop_auth_api_url() -> str:
    # get the base url from the configuration in settings.py
    hop_auth_base_url = settings.HOP_AUTH_BASE_URL

    # get the API version from the API
    hop_auth_api_version = 0  # TODO get from scimma_admin_base_url+'/api/version

    hop_auth_api_url = hop_auth_base_url + f'/api/v{hop_auth_api_version}'
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
