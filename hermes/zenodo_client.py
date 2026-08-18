"""
Thin client for the Zenodo (Sandbox) REST API, used by hermes.views.DoiMintApiView
to mint a DOI on behalf of an authenticated user for one or more Hermes messages.

This intentionally mirrors the request/response shape of Zenodo's deposit API
1:1 - create deposition -> set metadata -> upload file(s) -> publish - the same
flow validated standalone via zenodo_test_mint.py before this was wired into
Hermes.

Required Django settings (set in local_settings.py, same pattern as
SCIMMA_AUTH_* below them in settings.py):

    ZENODO_BASE_URL    e.g. https://sandbox.zenodo.org/api
    ZENODO_TOKEN       Zenodo personal access token (deposit:write, deposit:actions)
    ZENODO_COMMUNITY   (optional) community slug to request the deposition join
"""
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class ZenodoError(Exception):
    """Raised for any failure talking to Zenodo, with a human-readable message."""
    pass


def _base_url():
    base_url = getattr(settings, 'ZENODO_BASE_URL', None)
    token = getattr(settings, 'ZENODO_TOKEN', None)
    if not base_url or not token:
        raise ZenodoError(
            'Zenodo is not configured on this server. Set ZENODO_BASE_URL and '
            'ZENODO_TOKEN in local_settings.py.'
        )
    return base_url.rstrip('/')


def _auth_params():
    return {'access_token': settings.ZENODO_TOKEN}


def _raise_for_status(response, context):
    if not response.ok:
        detail = ''
        try:
            body = response.json()
            detail = body.get('message', '') or str(body)
        except ValueError:
            detail = response.text
        raise ZenodoError(f'Zenodo {context} failed (HTTP {response.status_code}): {detail}')


def create_deposition():
    """Step 1: Create an empty deposition draft. Returns the deposition dict."""
    url = f'{_base_url()}/deposit/depositions'
    response = requests.post(url, params=_auth_params(), json={})
    _raise_for_status(response, 'create deposition')
    return response.json()


def set_metadata(deposition_id, metadata):
    """
    Step 2: Attach metadata to a deposition.

    metadata: {
        'title': str,
        'description': str,
        'creators': [{'name': str, 'affiliation': str (optional)}, ...],
        'keywords': [str, ...] (optional),
    }
    """
    payload = {
        'metadata': {
            'title': metadata['title'],
            'upload_type': 'dataset',
            'description': metadata['description'],
            'creators': metadata['creators'],
        }
    }
    if metadata.get('keywords'):
        payload['metadata']['keywords'] = metadata['keywords']

    community = getattr(settings, 'ZENODO_COMMUNITY', None)
    if community:
        # Best-effort only: on current Zenodo (InvenioRDM), community membership
        # is a separate post-publish request/review step, not a metadata field.
        # This is harmless to include and may be honored on legacy instances.
        payload['metadata']['communities'] = [{'identifier': community}]

    url = f'{_base_url()}/deposit/depositions/{deposition_id}'
    response = requests.put(url, params=_auth_params(), json=payload)
    _raise_for_status(response, 'set metadata')
    return response.json()


def upload_file(bucket_url, filename, content_bytes):
    """
    Step 3: Upload a single file's raw bytes to the deposition's bucket.
    Zenodo's bucket API requires the generic application/octet-stream
    Content-Type regardless of the file's actual type.
    """
    url = f'{bucket_url}/{filename}'
    headers = {'Content-Type': 'application/octet-stream'}
    response = requests.put(url, params=_auth_params(), headers=headers, data=content_bytes)
    _raise_for_status(response, f'upload file {filename}')
    return response.json()


def publish_deposition(deposition_id):
    """
    Step 4: Publish the deposition. This mints the DOI and is irreversible
    (a new version must be created afterward; the record cannot be deleted).
    """
    url = f'{_base_url()}/deposit/depositions/{deposition_id}/actions/publish'
    response = requests.post(url, params=_auth_params())
    _raise_for_status(response, 'publish deposition')
    return response.json()


def mint_doi_for_package(metadata, files):
    """
    High-level orchestration used by the view.

    files: list of (filename: str, content_bytes: bytes)

    Returns the published deposition dict (includes 'doi' and
    'links'['record_html']).
    """
    deposition = create_deposition()
    set_metadata(deposition['id'], metadata)

    for filename, content_bytes in files:
        upload_file(deposition['links']['bucket'], filename, content_bytes)

    return publish_deposition(deposition['id'])