"""
Django settings for hermes_base project.

Generated by 'django-admin startproject' using Django 4.0.3.

For more information on this file, see
https://docs.djangoproject.com/en/4.0/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/4.0/ref/settings/
"""

import os
import logging.config
from pathlib import Path

from corsheaders.defaults import default_headers

from lcogt_logging import LCOGTFormatter


def str2bool(value):
    '''Convert a string value to a boolean'''
    value = value.lower()

    if value in ('t', 'true', 'y', 'yes', '1', ):
        return True

    if value in ('f', 'false', 'n', 'no', '0', ):
        return False

    raise RuntimeError(f'Unable to parse {value} as a boolean value')


# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/4.0/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'django-insecure-l9e!8@(p@p59st&xz1l8efd&4=10ms)2s=0jl9@wy$uh^h=f3p'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = str2bool(os.getenv('DEBUG', 'false'))

ALLOWED_HOSTS = ['*']

# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django_filters',
    'corsheaders',
    'django_extensions',  # for debuging: shell_plus management command
    'bootstrap4',
    'rest_framework',
    'rest_framework.authtoken',
    'mozilla_django_oidc',
    'tom_alertstreams',
    'hermes',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    "whitenoise.middleware.WhiteNoiseMiddleware",
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'hermes.middleware.SCiMMAAuthSessionRefresh',  # refresh SCiMMA Auth API tokens if necessary
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'hermes_base.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'hermes_base.wsgi.application'


# Database
# https://docs.djangoproject.com/en/4.0/ref/settings/#databases
#
# For development, override the DATABASES dictionary in your local_settings.py

DATABASES = {
   'default': {
       'ENGINE': os.getenv('DB_ENGINE', 'django.contrib.gis.db.backends.postgis'),
       'NAME': os.getenv('DB_NAME', 'hermes'),
       'USER': os.getenv('DB_USER', 'postgres'),
       'PASSWORD': os.getenv('DB_PASS', 'postgres'),
       'HOST': os.getenv('DB_HOST', '127.0.0.1'),
       'PORT': os.getenv('DB_PORT', '5432'),
   },
}


# Password validation
# https://docs.djangoproject.com/en/4.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/4.0/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.0/howto/static-files/

STATIC_URL = '/static/'
# STATIC_ROOT tells collectstatic where to copy all the static files that it collects.
STATIC_ROOT = '/static/'


# OpenID Connect (OIDC) Provider (OP) Configuration
# https://mozilla-django-oidc.readthedocs.io/en/stable/installation.html
#
# CILogin callbacks registered for HERMES (via SCiMMA/Chris Weaver) are:
#   http://127.0.0.1/auth/callback
#   http://127.0.0.1:8000/auth/callback
#   http://127.0.0.1:8001/auth/callback
#   http://hermes-dev.lco.gtn/auth/callback
#   http://hermes.lco.global/auth/callback
# TODO: are these values still current after swtich to Keycloak?


#
# Client ID (OIDC_RP_CLIENT_ID) and SECRET (OIDC_RP_CLIENT_SECRET)
# are how HERMES represents itself as the "relying party" (RP) to
# the SCiMMA Keycloak instance (login.scimma.org) (the OP). They should
# enter the environment as k8s secrets. Client ID and SECRET values were
# obtained from Keycloak via SCiMMA/Chris Weaver.
OIDC_RP_CLIENT_ID = os.getenv('OIDC_RP_CLIENT_ID', None)
OIDC_RP_CLIENT_SECRET = os.getenv('OIDC_RP_CLIENT_SECRET', None)
OIDC_RP_SIGN_ALGO = 'RS256'  # Signing Algorithm for Keycloak
OIDC_STORE_ID_TOKEN = True  # Forces OIDC login to store oidc_id_token in session dict

OIDC_OP_AUTHORIZATION_ENDPOINT = 'https://login.scimma.org/realms/SCiMMA/protocol/openid-connect/auth'
OIDC_OP_TOKEN_ENDPOINT = 'https://login.scimma.org/realms/SCiMMA/protocol/openid-connect/token'
OIDC_OP_USER_ENDPOINT = 'https://login.scimma.org/realms/SCiMMA/protocol/openid-connect/userinfo'
OIDC_OP_JWKS_ENDPOINT = 'https://login.scimma.org/realms/SCiMMA/protocol/openid-connect/certs'
# this method is invoke upon /logout -> mozilla_django_oidc.ODICLogoutView.post
OIDC_OP_LOGOUT_URL_METHOD = 'hermes.auth_backends.hopskotch_logout'
OIDC_OP_LOGOUT_ENDPOINT = 'https://login.scimma.org/realms/SCiMMA/protocol/openid-connect/logout'

# Set the OIDC login to be valid for 2 weeks since we disabled the refresh middleware
OIDC_RENEW_ID_TOKEN_EXPIRY_SECONDS = 60 * 60 * 24 * 14

# this tells mozilla-django-oidc that the front end can logout with a GET
# which allows the front end to use location.href to /auth/logout to logout.
ALLOW_LOGOUT_GET_METHOD = True

# https://docs.djangoproject.com/en/4.0/topics/auth/customizing/#specifying-authentication-backends
AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'hermes.auth_backends.HopskotchOIDCAuthenticationBackend',
    # 'mozilla_django_oidc.auth.OIDCAuthenticationBackend',
]

# Used to tell if this should save test messages or discard them
SAVE_TEST_MESSAGES = str2bool(os.getenv('SAVE_TEST_MESSAGES', 'true'))

# For getting TNS options values and submitting messages to TNS
TNS_BASE_URL = os.getenv('TNS_BASE_URL', 'https://sandbox.wis-tns.org/')
TNS_CREDENTIALS = {
    'id': int(os.getenv('TNS_BOT_ID', -1)),
    'name': os.getenv('TNS_BOT_NAME', ''),
    'api_token': os.getenv('TNS_BOT_API_TOKEN', '')
}

# SCiMMA Auth and Hopskotch specific configuration
SCIMMA_AUTH_BASE_URL = os.getenv('SCIMMA_AUTH_BASE_URL', default='https://admin.dev.hop.scimma.org/hopauth')  # for production
SCIMMA_AUTH_USERNAME = os.getenv('SCIMMA_AUTH_USERNAME', '')
SCIMMA_AUTH_PASSWORD = os.getenv('SCIMMA_AUTH_PASSWORD', '')
KAFKA_USER_AUTH_GROUP = os.getenv("KAFKA_USER_AUTH_GROUP", default="kafkaUsers")
SCIMMA_KAFKA_BASE_URL = os.getenv("SCIMMA_KAFKA_BASE_URL", default="kafka://dev.hop.scimma.org/")
SCIMMA_ARCHIVE_BASE_URL = os.getenv("SCIMMA_ARCHIVE_BASE_URL", default="https://archive-api.dev.hop.scimma.org/")


GCN_EMAIL = os.getenv('GCN_EMAIL', 'circulars@dev.gcn.nasa.gov')
GCN_BASE_URL = os.getenv('GCN_BASE_URL', 'https://dev.gcn.nasa.gov/')
HERMES_EMAIL_USERNAME = os.getenv('HERMES_EMAIL_USERNAME', 'hermes@lco.global')
HERMES_EMAIL_PASSWORD = os.getenv('HERMES_EMAIL_PASSWORD', "please set HERMES_EMAIL_PASSWORD env var")

# TODO: set up helm chart for dev and prod environments; this default works for local development
HERMES_FRONT_END_BASE_URL = os.getenv('HERMES_FRONT_END_BASE_URL', default='http://127.0.0.1:8001/')

# https://docs.djangoproject.com/en/4.0/ref/settings/#login-redirect-url
LOGIN_URL = '/'  # This is the default redirect URL for user authentication tests
LOGIN_REDIRECT_URL = '/login-redirect/'  # URL path to redirect to after login
LOGOUT_REDIRECT_URL = '/logout-redirect/'  # URL path to redirect to after logout
LOGIN_REDIRECT_URL_FAILURE = HERMES_FRONT_END_BASE_URL  # TODO: create login failure page
# TODO: handle login_failure !!

# Our hermes (django) backend is deployed behind nginx/guncorn. By default Django ignores
# the X-FORWARDED request headers generated. mozilla-django-oidc calls
# Django's request.build_absolute_uri method in such a way that the htttps
# request produces an http redirect_uri. So, we need to tell Django not to ignore
# the X-FORWARDED header and the protocol to use:
USE_X_FORWARDED_HOST = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Django REST Framework
# https://www.django-rest-framework.org/

REST_FRAMEWORK = {
    'DEFAULT_METADATA_CLASS': 'rest_framework.metadata.SimpleMetadata',
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework.authentication.SessionAuthentication',
        'hermes.auth_backends.HermesTokenAuthentication',
    ),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.LimitOffsetPagination",
    "PAGE_SIZE": 100,
}


# TOM-Alertstreams configuration
ALERT_STREAMS = [
    {
        'ACTIVE': True,
        'NAME': 'tom_alertstreams.alertstreams.hopskotch.HopskotchAlertStream',
        'OPTIONS': {
            'URL': SCIMMA_KAFKA_BASE_URL,
            'USERNAME': SCIMMA_AUTH_USERNAME,
            'PASSWORD': SCIMMA_AUTH_PASSWORD,
            # Group ID must be prefixed with SCiMMA SCRAM credential username to open the SCiMMA kafka stream
            'GROUP_ID': SCIMMA_AUTH_USERNAME + '-' + os.getenv('HOPSKOTCH_GROUP_ID', 'hermes-dev'),
            'TOPIC_HANDLERS': {
                '*': 'hermes.alertstream_handlers.ingest_from_hop.handle_generic_message',
                'hermes.*': 'hermes.alertstream_handlers.ingest_from_hop.handle_hermes_message',
                'mirror-test.*': 'hermes.alertstream_handlers.ingest_from_hop.ignore_message',
                'gcn.classic.voevent.*': 'hermes.alertstream_handlers.ingest_from_hop.ignore_message',
                'gcn.classic.text.LVC*': 'hermes.alertstream_handlers.ingest_from_hop.ignore_message',
                'gcn.classic.text.*': 'hermes.alertstream_handlers.ingest_from_hop.handle_gcn_notice_message',
                'microlensing.*': 'hermes.alertstream_handlers.ingest_from_hop.handle_hermes_message',
                'gcn.circular': 'hermes.alertstream_handlers.ingest_from_hop.ignore_message',
                'gcn.circulars': 'hermes.alertstream_handlers.ingest_from_hop.handle_gcn_circular_message',
                'igwn.gwalert*': 'hermes.alertstream_handlers.ingest_from_hop.handle_igwn_message'
            },
        },
    },
    {
        'ACTIVE': False,
        'NAME': 'tom_alertstreams.alertstreams.gcn.GCNClassicAlertStream',
        # The keys of the OPTIONS dictionary become (lower-case) properties of the AlertStream instance.
        'OPTIONS': {
            # see https://github.com/nasa-gcn/gcn-kafka-python#to-use for configuration details.
            'GCN_CLASSIC_CLIENT_ID': os.getenv('GCN_CLASSIC_CLIENT_ID', ''),
            'GCN_CLASSIC_CLIENT_SECRET': os.getenv('GCN_CLASSIC_CLIENT_SECRET', ''),
            'DOMAIN': 'gcn.nasa.gov',  # optional, defaults to 'gcn.nasa.gov'
            'CONFIG': {  # optional
                'group.id': os.getenv('GCN_CLASSIC_OVER_KAFKA_GROUP_ID', 'hermes-dev'),
                # 'auto.offset.reset': 'earliest',
                # 'enable.auto.commit': False
            },
            'TOPIC_HANDLERS': {
                'gcn.classic.text.LVC_COUNTERPART': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                'gcn.classic.text.ICECUBE_ASTROTRACK_BRONZE': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                'gcn.classic.text.ICECUBE_ASTROTRACK_GOLD': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                'gcn.classic.text.ICECUBE_CASCADE': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.INTEGRAL_POINTDIR': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.FERMI_GBM_ALERT': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.AGILE_MCAL_ALERT': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.SWIFT_UVOT_DBURST': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.SWIFT_POINTDIR': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.SWIFT_ACTUAL_POINTDIR': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.GRB_CNTRPART': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.AMON_NU_EM_COINC': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.COINCIDENCE': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.FERMI_GBM_FIN_POS': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.FERMI_GBM_FLT_POS': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.FERMI_GBM_GND_POS': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.FERMI_GBM_SUBTHRESH': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.FERMI_LAT_MONITOR': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.FERMI_LAT_OFFLINE': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.FERMI_POINTDIR': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.GECAM_FLT': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.GECAM_GND': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.HAWC_BURST_MONITOR': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.INTEGRAL_OFFLINE': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.INTEGRAL_REFINED': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.INTEGRAL_SPIACS': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.INTEGRAL_WAKEUP': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.INTEGRAL_WEAK': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.KONUS_LC': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.MAXI_KNOWN': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.MAXI_UNKNOWN': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.SK_SN': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.SNEWS': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.SWIFT_BAT_GRB_LC': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.SWIFT_BAT_QL_POS': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.SWIFT_BAT_SCALEDMAP': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.SWIFT_BAT_TRANS': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.SWIFT_FOM_OBS': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.SWIFT_SC_SLEW': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.SWIFT_TOO_FOM': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.SWIFT_TOO_SC_SLEW': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.SWIFT_UVOT_DBURST_PROC': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.SWIFT_UVOT_EMERGENCY': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.SWIFT_UVOT_FCHART': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.SWIFT_UVOT_FCHART_PROC': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.SWIFT_UVOT_POS': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.SWIFT_XRT_CENTROID': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.SWIFT_XRT_IMAGE': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.SWIFT_XRT_IMAGE_PROC': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.SWIFT_XRT_LC': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.SWIFT_XRT_POSITION': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.SWIFT_XRT_SPECTRUM': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.SWIFT_XRT_SPECTRUM_PROC': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.SWIFT_XRT_SPER': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.SWIFT_XRT_SPER_PROC': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.SWIFT_XRT_THRESHPIX': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message',
                # 'gcn.classic.text.SWIFT_XRT_THRESHPIX_PROC': 'hermes.alertstream_handlers.ingest_from_gcn_classic.handle_message'
            },
        },
    }
]


# Other OAuth Client definitions
AUTHLIB_OAUTH_CLIENTS = {
    'gcn': {
        'client_id': os.getenv('GCN_OAUTH_CLIENT_ID', ''),
        'client_secret': os.getenv('GCN_OAUTH_CLIENT_SECRET', ''),
        'server_metadata_url': os.getenv('GCN_OAUTH_SERVER_METADATA_URL', ''),
    }
}


#
# CORS configuration
# https://pypi.org/project/django-cors-headers/
#

CORS_ORIGIN_ALLOW_ALL = True
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = list(default_headers) + [
    # add custom headers here
]


# Default primary key field type
# https://docs.djangoproject.com/en/4.0/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

CACHES = {
     'default': {
         'BACKEND': os.getenv('CACHE_BACKEND', 'django.core.cache.backends.dummy.DummyCache'),
         'LOCATION': os.getenv('CACHE_LOCATION', 'default-cache')
     }
}

#
# Logging

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'default': {
            '()': LCOGTFormatter
        }
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'default'
        },
    },
    'loggers': {
        '': {
            'handlers': ['console'],
            'level': 'INFO',
            # 'level': 'DEBUG'
        },
        'mozilla_django_oidc': {
            'handlers': ['console'],
            'level': 'INFO'
        },
    }
}
logging.config.dictConfig(LOGGING)

try:
    logging.info('Looking for local_settings.')
    from local_settings import *  # noqa
except ImportError:
    logging.info('No local_settings found.')
    pass
