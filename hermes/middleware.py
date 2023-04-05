import logging
import datetime

from django.utils import dateparse
from django.contrib.auth import logout
from django.http import HttpResponse

from hermes.brokers import hopskotch
from hermes.auth_backends import hopskotch_logout


logger = logging.getLogger(__name__)
#logger.setLevel(logging.DEBUG)

class SCiMMAAuthSessionRefresh:
    def __init__(self, get_response):
        self.get_response = get_response

    def _is_expired(self, expiration: datetime.datetime) -> bool:
        """Return True if expiration is in the past, or within the next 15 minutes.

        Reminder: datetimes grow into the future. So, datetime.datetime.now()
        is less than future datetimes. Or, if now() is greater than an expiration
        datetime, then that expiration datetime is in the past (expired).
        """
        some_mintues_from_now = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=15)
        return some_mintues_from_now > expiration # > means True if expiration is in past

    def refresh_user_token(self, request):
        """Refresh the SCiMMA Auth User API token in the request.session.

        We might need to refresh the Hermes service account SCiMMA Auth API token along the way,
        since admin privilidges are required to get the User API token
        """
        logger.debug(f'Refreshing SCiMMA Auth API token for User {request.user} ({request.user.username})')
        hermes_api_token = hopskotch.get_hermes_api_token()
        user_api_token, user_api_token_expiration = hopskotch.get_user_api_token(request.user.username, hermes_api_token)
        request.session['user_api_token'] = user_api_token
        request.session['user_api_token_expiration'] = user_api_token_expiration


    def __call__(self, request):
        # Code to be executed for each request before
        # the view (and later middleware) are called.
        logger.debug(f'maintaining SCiMMA Auth API tokens in Session...')

        # First check the oidc token expiration - if expired, return a HTTP 401 to indicate client should logout
        oidc_expiration_seconds = request.session.get('oidc_id_token_expiration')
        if oidc_expiration_seconds:
            if datetime.datetime.utcnow() > datetime.datetime.fromtimestamp(float(oidc_expiration_seconds)):
                logger.debug(f"OIDC login has expired for user {request.user}, forcing hop logout and returning 401")
                hopskotch_logout(request)
                logout(request)
                return HttpResponse('Unauthorized', status=401)

        # IMPORTANT: we only check the user api token here, but that might trigger a hermes_api_token
        # get/refresh, and we need that to authenticate users in auth_backends.
        if request.user.username:
            user_api_token_expiration_str: str = request.session.get('user_api_token_expiration', None)
            if user_api_token_expiration_str:
                user_api_token_expiration: datetime.datetime = dateparse.parse_datetime(user_api_token_expiration_str)
                need_new_user_api_token = self._is_expired(user_api_token_expiration)
            else:
                need_new_user_api_token = True
            if need_new_user_api_token:
                logger.debug(f'New SCiMMA Auth API user token needed for {request.user} ({request.user.username})')
                self.refresh_user_token(request)
            else:
                # the api_token is either not expired or non-existent (for the AnonymousUser)
                logger.debug(f'SCiMMA Auth API token for {request.user} ({request.user.username}): refresh not needed.')
        else:
            logger.debug(f'No user is logged in, so not refreshing user token.')

        response = self.get_response(request)  # pass the request to the next Middleware in the list

        # Code to be executed for each request/response after
        # the view is called.
        return response
