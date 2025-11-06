"""hermes_base URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import include, path
from rest_framework import routers
from hermes import views

import logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


router = routers.DefaultRouter()
router.register(r'messages', views.MessageViewSet, 'messages')
router.register(r'nonlocalizedevents', views.NonLocalizedEventViewSet, 'events')
router.register(r'nonlocalizedeventsequence', views.NonLocalizedEventSequenceViewSet, 'eventsequences')
router.register(r'targets', views.TargetViewSet, 'targets')
router.register(r'topics', views.TopicViewSet, basename='topic')
router.register(r'submit_message', views.SubmitHermesMessageViewSet, 'submit_message')

urlpatterns = [
    path('admin/', admin.site.urls, name='admin'),
    path('auth/', include('mozilla_django_oidc.urls')),
    path('gcn-auth/login', views.GcnLoginRedirectView.as_view(), name='gcn-login'),
    path('gcn-auth/authorize', views.GcnAuthorizeView.as_view(), name='gcn-authorize'),
    path('', include('hermes.urls')),
    path('api/v0/', include(router.urls)),
    path('api/v0/query/', views.QueryApiView.as_view(), name='query'),
    path('api/v0/heartbeat/', views.HeartbeatApiView.as_view(), name='heartbeat'),
    path('api/v0/profile/', views.ProfileApiView.as_view(), name='profile'),
    path('api/v0/tns_options/', views.TNSOptionsApiView.as_view(), name='tns_options'),
    path('api/v0/revoke_api_token/', views.RevokeApiTokenApiView.as_view(), name='revoke_api_token'),
    path('api/v0/revoke_hop_credential/', views.RevokeHopCredentialApiView.as_view(), name='revoke_hop_credential')
]

# mozilla_django_oidc.urls provides:
#  oidc_authentication_callback
#  oidc_authentication_init
#  oidc_logout
