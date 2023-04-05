import logging

from django.conf import settings
from django.core.exceptions import PermissionDenied

from hop.auth import Auth
import jsons
from mozilla_django_oidc import auth

from hermes.brokers import hopskotch
from hermes.models import Profile

logger = logging.getLogger(__name__)
#logger.setLevel(logging.DEBUG)

class NotInKafkaUsers(PermissionDenied):
    """COManage maintains a kafkaUsers group that a User must
    belong to in order to submit to the Hopskotch kafka steam.
    """
    pass


class HopskotchOIDCAuthenticationBackend(auth.OIDCAuthenticationBackend):
    """Subclass Mozilla's OIDC Auth backend for custom hopskotch behavior.

    `mozilla_django_oidc.auth.OIDCAuthenticationBackend` is a subclass of
    `django.contrib.auth.backends.ModelBackend`.

    For the Keycloak OIDC Provider (login.scimma.org), the claims passed to many of
    these methods looks like this:
        claims = {
            'sub': '0d988bdd-ec83-420d-8ded-dd9091318c24',
            'name': 'Lindy Lindstrom',
            'preferred_username': 'llindstrom@lco.global',
            'given_name': 'Lindy',
            'family_name': 'Lindstrom',
            'email': 'llindstrom@lco.global'
            'email_verified': False,
            'is_member_of': ['/Hopskotch Users', '/SCiMMA Developers'],
        }
    """
    def __init__(self):
        auth.OIDCAuthenticationBackend.__init__(self)
        self.kafka_user_auth_group = settings.KAFKA_USER_AUTH_GROUP
        logger.debug(f'HopskotchOIDCAuthenticationBackend.__init__')


    def filter_users_by_claims(self, claims):
        """Return all users matching the username extracted from the claims via
        `self.get_username`.

        Overrides base class method.
        """
        logger.debug(f'HopskotchOIDCAuthenticationBackend.filter_users_by_claims: {claims}')
        username = self.get_username(claims)
        if not username:
            return self.UserModel.objects.none()
        return self.UserModel.objects.filter(username=username)


    def get_username(self, claims):
        """Return the username in the claims.

        For the Keycloak OIDC provider (login.scimma.org), the value of the
        'sub' key is the username.

        Overrides base class method.
        """
        return claims.get('sub')


    def get_email(self, claims):
        """Extract email from claims"""
        email = ""
        if "email" in claims:
            email = claims.get("email")
        elif "email_list" in claims:
            email = claims.get("email_list")

        if isinstance(email, list):
            email = email[0]
        return email


    def verify_claims(self, claims):
        """
        NB:  SCiMMA Auth (scimma-admin) enforces Hopskotch users being in kafkaUsers group
        but since they are doing that HERMES doesn't have to. See scimma-admin repo for how
        that check was done.

        Overrides base class method.
        """
        logger.debug(f'HopskotchOIDCAuthenticationBackend.verify_claims claims: {claims}')
        # Value for 'is_member_of' key is list(COManage groups)
        if "is_member_of" not in claims:
            logger.error(f"Account is missing LDAP claims; claims={claims}")
            msg = "Your account is missing LDAP claims. Are you sure you used the account you use for SCIMMA?"
            raise PermissionDenied(msg)

        if "email" in claims:
            return True
        if "email_list" in claims and len(claims.get("email_list", [])) > 0:
            return True

        msg = f"Your account is missing an email claim; claims={claims}"
        logger.error(f"Account is missing LDAP email claim; claims={claims}")
        raise PermissionDenied(msg)


    def create_user(self, claims):
        """Create a HERMES Django User with
          * username given by OIDC Provider claims['sub']
          * email given by claims['email'] or claims['email_list][0]
          * is_staff is True for SCiMMA DevOps members

        HERMES requires that a SCiMMA Auth User exists so it can access the User's
        Group and Topic permission stored there. So, before creating the Hermes User,
        pass these claims to hopskotch.get_or_create_user to make sure this User exists
        there and, if not, use the API to create it.

        Overrides base class method.
        """
        logger.debug(f'HopskotchOIDCAuthenticationBackend.create_user claims: {claims}')

        username = self.get_username(claims)
        if "email" in claims:
            email = claims.get("email")
        elif "email_list" in claims:
            email = claims.get("email_list")

        if isinstance(email, list):
            email = email[0]

        # make sure the User has been created in SCiMMA Auth
        scimma_auth_user, created = hopskotch.get_or_create_user(claims)
        if created:
            logger.info(f'create_user - Created SCiMMA Auth User {username}')
        else:
            logger.info(f'create_user - Found existing SCiMMA Auth User {scimma_auth_user}')

        # now make our local HERMES User
        new_user = self.UserModel.objects.create(
            username=username,
            email=self.get_email(claims),
            is_staff=is_member_of(claims, '/SCiMMA Developers'),
            first_name=claims.get('given_name', ''),
            last_name=claims.get('family_name', ''),
        )
        # Initialize a profile here for the new user account
        Profile.objects.get_or_create(user=new_user)
        logger.debug(f'HopskotchOIDCAuthenticationBackend.create_user: new HERMES User: {new_user} with claims: {claims}')
        logger.debug(f'HopskotchOIDCAuthenticationBackend.create_user: UserModel: {self.UserModel}')

        return new_user

    
    def update_user(self, user, claims):
        """Update existing user with new claims, if necessary save, and return user

        Base class extensions:
          * save first_name, last_name, email, is_staff
          * check that SCiMMA Auth User exista and create if necessary.

        Overrides base class method.
        """
        logger.info(f'HopskotchOIDCAuthenticationBackend.update_user {user} with claims: {claims}')

        # make sure the User exists in SCiMMA Auth
        scimma_auth_user, created = hopskotch.get_or_create_user(claims)
        if created:
            logger.info(f'update_user - Created SCiMMA Auth User {scimma_auth_user}')
        else:
            logger.info(f'update_user - Found existing SCiMMA Auth User {scimma_auth_user}')

        # NOTE: if we ever wanted to save the claims in the session, this (and create_user) would
        #   be the place to do it.

        user.first_name = claims.get('given_name', '')
        user.last_name = claims.get('family_name', '')
        user.email = self.get_email(claims)
        user.is_staff = is_member_of(claims, '/SCiMMA Developers')
        user.save()

        # Check and create the profile here (if it hasn't been created before)
        Profile.objects.get_or_create(user=user)

        return user


    def authenticate(self, request, **kwargs):
        """Override this method to insert Hop Auth data into the session to be used
        in the Views that submit alerts to Hopskotch.

        Notes:
         * the request.session is a SessionStore instance
         * the user is a django.contrib.auth.User instance
         * the safe way to the username is user.get_username()

        Extends base class method.
        """
        user = super().authenticate(request, **kwargs) # django.contrib.auth.models.User

        hermes_api_token = hopskotch.get_hermes_api_token()
        hop_auth = hopskotch.authorize_user(user.get_username(), hermes_api_token)

        # Auth instances are not trivially serializable with json.dumps. So use jsons.dump:
        request.session['hop_user_auth_json'] = jsons.dump(hop_auth)

        return user # mimic super()


def hopskotch_logout(request):
    """Do the actions required when the user logs out of HERMES (and thus hopskotch).
    (This is the OIDC_OP_LOGOUT_URL_METHOD).

    1. call hopskotch.deauthorize_user()

    NOTES:
      * must return the logout URL
      * called as a hook (via settings.OIDC_OP_LOGOUT_URL_METHOD) from
        mozilla_django_oidc.OIDCLogoutView.post() (from /logout endpoint)
      * the request.user is a django.utils.functional.SimpleLazyObject which is a wrapper
        around a django.contrib.auth.User (see SO:10506766).
    """
    # hop_user_auth_json added to Session dict in AuthenticationBackend.authenticate
    try:
        hop_user_auth: Auth = jsons.load(request.session['hop_user_auth_json'], Auth)
        user_api_token = request.session['user_api_token']
        hopskotch.deauthorize_user(request.user.username, hop_user_auth, user_api_token)
    except KeyError as err:
        logger.error(f'No hop.auth.Auth instance in Session. Clean up SCiMMA Auth manually. session: {request.session}')

    return settings.LOGOUT_REDIRECT_URL


def is_member_of(claims, group):
    return group in claims.get('is_member_of', [])
