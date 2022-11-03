"""
Django settings for hermes_base project.

Generated by 'django-admin startproject' using Django 4.0.3.

For more information on this file, see
https://docs.djangoproject.com/en/4.0/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/4.0/ref/settings/
"""

from cmath import log
import os
import logging.config
from pathlib import Path

from corsheaders.defaults import default_headers

from lcogt_logging import LCOGTFormatter


# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/4.0/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'django-insecure-l9e!8@(p@p59st&xz1l8efd&4=10ms)2s=0jl9@wy$uh^h=f3p'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = ['*']


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'corsheaders',
    'django_extensions',  # for debuging: shell_plus management command
    'bootstrap4',
    'rest_framework',
    'mozilla_django_oidc',
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
    'mozilla_django_oidc.middleware.SessionRefresh',  # make sure User's ID token is still valid
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
       'ENGINE': os.getenv('DB_ENGINE', 'django.db.backends.postgresql'),
       'NAME': os.getenv('DB_NAME', 'hermes'),
       'USER': os.getenv('DB_USER', 'postgres'),
       'PASSWORD': os.getenv('DB_PASS', ''),
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
STATIC_ROOT = os.path.join(BASE_DIR, 'static')


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
OIDC_RP_SIGN_ALGO = 'RS256' # Signing Algorithm for Keycloak

OIDC_OP_AUTHORIZATION_ENDPOINT = 'https://login.scimma.org/realms/SCiMMA/protocol/openid-connect/auth'
OIDC_OP_TOKEN_ENDPOINT = 'https://login.scimma.org/realms/SCiMMA/protocol/openid-connect/token'
OIDC_OP_USER_ENDPOINT = 'https://login.scimma.org/realms/SCiMMA/protocol/openid-connect/userinfo'
OIDC_OP_JWKS_ENDPOINT = 'https://login.scimma.org/realms/SCiMMA/protocol/openid-connect/certs'
# this method is invoke upon /logout -> mozilla_django_oidc.ODICLogoutView.post
OIDC_OP_LOGOUT_URL_METHOD = 'hermes.auth_backends.hopskotch_logout'

# this tells mozilla-django-oidc that the front end can logout with a GET
# which allows the front end to use location.href to /auth/logout to logout.
ALLOW_LOGOUT_GET_METHOD = True

# https://docs.djangoproject.com/en/4.0/topics/auth/customizing/#specifying-authentication-backends
AUTHENTICATION_BACKENDS = [
    'hermes.auth_backends.HopskotchOIDCAuthenticationBackend',
    # 'mozilla_django_oidc.auth.OIDCAuthenticationBackend',
]


# SCiMMA_admin and Hopskotch specific configuration
#HOP_AUTH_BASE_URL = 'http://127.0.0.1:8000/hopauth'  # for locally running scimma_admin (hopauth)
#HOP_AUTH_BASE_URL = 'https://admin.dev.hop.scimma.org/hopauth'  # for devlopment scimma_admin (hopauth)
HOP_AUTH_BASE_URL = os.getenv('HOP_AUTH_BASE_URL', default='https://my.hop.scimma.org/hopauth')  # for production scimmma_admin (hopauth)
KAFKA_USER_AUTH_GROUP = os.getenv("KAFKA_USER_AUTH_GROUP", default="kafkaUsers")

# TODO: set up helm chart for dev and prod environments; this default works for local development
HERMES_FRONT_END_BASE_URL = os.getenv('HERMES_FRONT_END_BASE_URL', default='http://127.0.0.1:8080/')

# https://docs.djangoproject.com/en/4.0/ref/settings/#login-redirect-url
LOGIN_URL ='/'  # This is the default redirect URL for user authentication tests
LOGIN_REDIRECT_URL = '/login-redirect/'  # URL path to redirect to after login
LOGOUT_REDIRECT_URL = '/logout-redirect/' # URL path to redirect to after logout
LOGIN_REDIRECT_URL_FAILURE = HERMES_FRONT_END_BASE_URL # TODO: create login failure page
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
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 10,
}


#
# CORS configuration
# https://pypi.org/project/django-cors-headers/
#

CORS_ORIGIN_ALLOW_ALL = True
CORS_ALLOW_HEADERS = list(default_headers) + [
    # add custom headers here
]


# Default primary key field type
# https://docs.djangoproject.com/en/4.0/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

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
            #'level': 'DEBUG'
        },
        'mozilla_django_oidc': {
            'handlers': ['console'],
            'level': 'INFO'
        },
    }
}
logging.config.dictConfig(LOGGING)

#logging.debug(f'Allowed CORES Headers: {CORS_ALLOW_HEADERS}')

try:
    logging.info('Looking for local_settings.')
    from local_settings import *  # noqa
except ImportError:
    logging.info('No local_settings found.')
    pass
