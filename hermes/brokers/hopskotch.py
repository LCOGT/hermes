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



