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
    'bootstrap4',
    'rest_framework',
    'mozilla_django_oidc',
    'hermes',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    "whitenoise.middleware.WhiteNoiseMiddleware",
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    #'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
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

# Client ID and SECRET are how HERMES represents itself to CILogon.org (the OP).
# Client ID and SECRET values obtained from CILogon.org via SCiMMA/Chris Weaver.
# Callbacks registered for HERMES are:
#   http://127.0.0.1/auth/callback
#   http://127.0.0.1:8000/auth/callback
#   http://hermes-dev.lco.gtn/auth/callback
#   http://hermes.lco.global/auth/callback
OIDC_RP_CLIENT_ID = os.getenv('OIDC_RP_CLIENT_ID', 'you must set OIDC_RP_CLIENT_ID')
OIDC_RP_CLIENT_SECRET = os.getenv('OIDC_RP_CLIENT_SECRET', 'you must set OIDC_RP_CLIENT_SECRET')

# Signing Algorithm for CILogon
OIDC_RP_SIGN_ALGO = 'RS256'
OIDC_RP_JWKS_ENDPOINT = 'https://cilogon.org/oath2/certs'

# more OIDC config
OIDC_OP_AUTHORIZATION_ENDPOINT = 'https://cilogon.org/authorize/'
OIDC_OP_TOKEN_ENDPOINT = 'https://cilogon.org/oauth2/token'
OIDC_OP_USER_ENDPOINT = 'https://cilogon.org/oauth2/userinfo'

AUTHENTICATION_BACKENDS = (
    'mozilla_django_oidc.auth.OIDCAuthenticationBackend',
)

LOGIN_URL ='/hermes/login'  # TODO: how is this used?
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/hermes/logout'
LOGIN_REDIRECT_URL_FAILURE = '/hermes/login_failure'


# Django REST Framework
# https://www.django-rest-framework.org/

REST_FRAMEWORK = {
    'DEFAULT_METADATA_CLASS': 'rest_framework.metadata.SimpleMetadata',
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 10,
}

CORS_ORIGIN_ALLOW_ALL = True

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
