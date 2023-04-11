import logging
import datetime

from django.contrib.auth import logout
from django.http import HttpResponse

logger = logging.getLogger(__name__)


class SCiMMAAuthSessionRefresh:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Code to be executed for each request before
        # the view (and later middleware) are called.
        logger.debug(f'Checking Keycloak login OIDC token expiration...')

        # Check the oidc token expiration - if expired, return a HTTP 401 to indicate client should logout
        oidc_expiration_seconds = request.session.get('oidc_id_token_expiration')
        if oidc_expiration_seconds:
            if datetime.datetime.utcnow() > datetime.datetime.fromtimestamp(float(oidc_expiration_seconds)):
                logger.debug(f"OIDC login has expired for user {request.user}, forcing logout and returning 401")
                logout(request)
                return HttpResponse('Unauthorized', status=401)

        response = self.get_response(request)  # pass the request to the next Middleware in the list

        # Code to be executed for each request/response after
        # the view is called.
        return response
