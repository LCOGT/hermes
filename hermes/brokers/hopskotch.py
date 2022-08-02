"""hermes/brokers/hopskotch.py

Interaction with the HOPSKOTCH Kafka stream and it's associated APIs happen here.

After the SCIMMA_ADMIN_BASE_URL is defined in settings.py, this module encodes specifics
of the scimma_admin (hopauth) API that goes beyond that configuration. That is, this module
is intended depend on HOPSKOTCH/hopauth/scimma_admin specifics. For example, how the versioning
works, etc
"""
import logging
import os
import requests

from django.conf import settings

from hop.auth import Auth

from rest_framework import status
from rest_framework.response import Response

import scramp



logger = logging.getLogger(__name__)

#  from the environment, get the HERMES service account credentials for HopAuth (scimma-admin).
HOP_USERNAME = os.getenv('HOP_USERNAME', 'set the HOP_USENAME for the HERMES service account')
HOP_PASSWORD = os.getenv('HOP_PASSWORD', 'set the HOP_PASSWORD for the HERMES service account')

def get_hop_auth_api_url() -> str:
    """Use the HOP_AUTH_BASE_URL from settings.py and construct the API url from that.
    """
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
    rest_token = scram_resp2.json()["token"]
    logger.info(f'get_hermes_api_token: Token issued: {rest_token}')
    rest_token = f'Token {rest_token}'  # Django wants this (Token<space>) prefix
    return rest_token
