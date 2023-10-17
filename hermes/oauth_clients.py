from django.conf import settings
from datetime import datetime
import logging
from django.utils import timezone
from authlib.integrations.django_client import OAuth
from hermes.models import OAuthToken

logger = logging.getLogger(__name__)


def update_token(user, integrated_app, token_details):
    """ Called on authentication of an oauth service, this method creates or updates the already
        created OAuthToken with the details received from the authentication service.
    """
    # enforce the restriction of only one stored token per user and integrated app
    OAuthToken.objects.update_or_create(user=user, integrated_app=integrated_app, defaults={
        'access_token': token_details.get('access_token'),
        'refresh_token': token_details.get('refresh_token'),
        'token_type': token_details.get('token_type'),
        'expires_at': datetime.fromtimestamp(token_details.get('expires_at')).replace(tzinfo=timezone.utc),
        'expires_in': token_details.get('expires_in')
    })


def refresh_token(user, token):
    """ Takes in a user and token object and attempts to refresh the token. The token object must
        have a valid refresh_token stored in it, and the oauth_client must support refreshing its
        access_token. Updates the access_token and expiration times if successful, and returns back
        the updated token object.
    """
    logger.info(f"Refreshing {token.integrated_app} token for user {user.username}")
    oauth_client = oauth_clients.get(token.integrated_app)
    if oauth_client:
        # The refreshed token details contain only an access token and expiration
        token_details = oauth_client.fetch_access_token(refresh_token=token.refresh_token, grant_type='refresh_token')
        if not token_details:
            # If the token_details are not returned, assume the refresh token is bad and delete the entire OAuthToken
            # TODO: I don't actually know what is returned if the refresh_token expires so this might not work!
            token.delete()
            return None
        token.access_token = token_details.get('access_token')
        token.expires_at = datetime.fromtimestamp(token_details.get('expires_at')).replace(tzinfo=timezone.utc)
        token.expires_in = token_details.get('expires_in')
        token.save()
    return token


def get_access_token(user, integrated_app):
    """ Returns a valid access_token given a user and an integrated app to find
        an oauth token for. Refreshes the token if it is expired if possible.
        If no token exists, returns None.
    """
    try:
        token = OAuthToken.objects.get(user=user, integrated_app=integrated_app)
    except OAuthToken.DoesNotExist:
        return None
    if token.is_expired():
        token = refresh_token(user, token)
    if token:
        return token.access_token
    return None


oauth = OAuth()
gcn_client = oauth.register(
    name='gcn',
    server_metadata_url=settings.AUTHLIB_OAUTH_CLIENTS.get('gcn', {}).get('server_metadata_url'),
    client_kwargs={'scope': 'openid gcn.nasa.gov/circular-submitter email'}
)

# Clients can either be called using oauth.gcn, gcn_client, or by adding them to this oauth_clients dict
oauth_clients = {
    OAuthToken.IntegratedApps.GCN: gcn_client
}
