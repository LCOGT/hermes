import logging
import datetime

from django.utils import dateparse

from hermes.brokers import hopskotch

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


    def refresh_hermes_token(self, request):
        logger.debug(f'Refreshing SCiMMA Auth API token for Hermes service account.')
        hermes_api_token, hermes_api_token_expiration = hopskotch.get_hermes_api_token()
        request.session['hermes_api_token'] = hermes_api_token
        request.session['hermes_api_token_expiration'] = hermes_api_token_expiration


    def refresh_user_token(self, request):
        """Refresh the SCiMMA Auth User API token in the request.session.

        We might need to refresh the Hermes service account SCiMMA Auth API token along the way,
        since admin privilidges are required to get the User API token
        """
        logger.debug(f'Refreshing SCiMMA Auth API token for User.')

        # get the hermes service account API token and check it's expiration status
        hermes_api_token_expiration_str: str = request.session.get('hermes_api_token_expiration', None)
        if hermes_api_token_expiration_str:
            hermes_api_token_expiration: datetime.datetime = dateparse.parse_datetime(hermes_api_token_expiration_str)
            need_new_hermes_api_token = self._is_expired(hermes_api_token_expiration)
        else:
            need_new_hermes_api_token = True
        
        if need_new_hermes_api_token:
            logger.debug(f'New SCiMMA Auth API token for Hermes service account needed.')
            self.refresh_hermes_token(request)
        else:
            logger.debug(f'SCiMMA Auth API token for Hermes service account up-to-date.')
        
        username = request.user.username
        hermes_api_token = request.session['hermes_api_token']
        user_api_token, user_api_token_expiration = hopskotch.get_user_api_token(username, hermes_api_token)
        request.session['user_api_token'] = user_api_token
        request.session['user_api_token_expiration'] = user_api_token_expiration


    def __call__(self, request):
        # Code to be executed for each request before
        # the view (and later middleware) are called.
        logger.debug(f'maintaining SCiMMA Auth API tokens in Session...')

        user_api_token_expiration_str: str = request.session.get('user_api_token_expiration', None)
        if user_api_token_expiration_str:
            user_api_token_expiration: datetime.datetime = dateparse.parse_datetime(user_api_token_expiration_str)
            need_new_user_api_token = self._is_expired(user_api_token_expiration)
        else:
            need_new_user_api_token = True
        
        if need_new_user_api_token:
            logger.debug(f'New SCiMMA Auth API user token needed.')
            self.refresh_user_token(request)
        else:
            logger.debug(f'SCiMMA Auth API token for {request.user.username} up-to-date.')

        response = self.get_response(request)  # pass the request to the next Middleware in the list

        # Code to be executed for each request/response after
        # the view is called.

        return response
