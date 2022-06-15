from django.conf import settings
from django.core.exceptions import SuspiciousOperation, PermissionDenied

import logging
import secrets

from mozilla_django_oidc import auth

logger = logging.getLogger(__name__)

class NotInKafkaUsers(PermissionDenied):
    """COManage maintains a kafkaUsers group that a User must
    belong to in order to submit to the Hopskotch kafka steam.
    """
    pass


class HopskotchOIDCAuthenticationBackend(auth.OIDCAuthenticationBackend):
    """Subclass Mozilla's OIDC Auth backend for custom hopskotch behavior.
    """

    def __init__(self):
        auth.OIDCAuthenticationBackend.__init__(self)
        self.kafka_user_auth_group = settings.KAFKA_USER_AUTH_GROUP
        logger.info(f'HopskotchOIDCAuthenticationBackend.__init__')

    def filter_users_by_claims(self, claims):
        logger.info(f'HopskotchOIDCAuthenticationBackend.filter_users_by_claims: {claims}')
        username = claims.get("vo_person_id")
        if not username:
            return self.UserModel.objects.none()
        return self.UserModel.objects.filter(username=username)

    def get_username(self, claims):
        """Return the vo_person_id in the claims
        """
        logger.info(f'HopskotchOIDCAuthenticationBackend.get_username')
        return claims.get("vo_person_id")

    def verify_claims(self, claims):
        """
        """
        logger.info(f'HopskotchOIDCAuthenticationBackend.verify_claims')
        # Value for 'is_member_of' key is  list(COManage groups)
        if "is_member_of" not in claims:
            log_event_id = secrets.token_hex(8)
            msg = f"Your account is missing LDAP claims. Are you sure you used the account you use for SCIMMA? Error ID: {log_event_id}"
            logger.error(f"account is missing LDAP claims, error_id={log_event_id}, claims={claims}")
            raise PermissionDenied(msg)

        for group in [self.kafka_user_auth_group]:
            if not is_member_of(claims, group):
                name = claims.get('vo_display_name', 'Unknown')
                id = claims.get('vo_person_id', 'Unknown')
                email = claims.get('email', 'Unknown')
                msg = f"User vo_display_name={name}, vo_person_id={id}, email={email} is not in {group}, but requested access"
                logger.error(msg)
                raise NotInKafkaUsers(msg)

        if "email" in claims:
            return True
        if "email_list" in claims and len(claims.get("email_list", [])) > 0:
            return True

        log_event_id = secrets.token_hex(8)
        msg = f"Your account is missing an email claim. Error ID: {log_event_id}"
        logger.error(f"account is missing LDAP email claims, error_id={log_event_id}, claims={claims}")
        raise PermissionDenied(msg)

    def create_user(self, claims):
        """Create a Django User with
             * username given by OIDC Provider claims['vo_person_id']
             * email given by claims['email'] or claims['email_list][0]
             * is_staff is True for SCiMMA DevOps members
        """
        logger.info(f'HopskotchOIDCAuthenticationBackend.create_user')
        if "email" in claims:
            email = claims.get("email")
        elif "email_list" in claims:
            email = claims.get("email_list")

        if isinstance(email, list):
            email = email[0]

        new_user = self.UserModel.objects.create(
            username=claims["vo_person_id"],
            email=email,
            is_staff=is_member_of(claims, 'CO:COU:SCiMMA DevOps:members:active'),
        )
        logger.info(f'HopskotchOIDCAuthenticationBackend.create_user: new_user: {new_user}')
        logger.info(f'HopskotchOIDCAuthenticationBackend.create_user: UserModel: {self.UserModel}')

        return new_user


def is_member_of(claims, group):
    return group in claims.get('is_member_of', [])
