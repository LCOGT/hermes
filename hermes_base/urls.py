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
    path('', views.MessageListView.as_view(), name='index'),
    path('admin/', admin.site.urls, name='admin'),
    path('auth/', include('mozilla_django_oidc.urls')),
    path('', include('hermes.urls')),
    path('api/v0/', include(router.urls)),
    path('api/v0/profile/', views.ProfileApiView.as_view(), name='profile')
]

# mozilla_django_oidc.urls provides:
#  oidc_authentication_callback
#  oidc_authentication_init
#  oidc_logout
