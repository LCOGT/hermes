from pydoc import pathdirs
from django.urls import path
from hermes import views

urlpatterns = [
    path('messages', views.MessageListView.as_view(), name='message-list'),
    path('messages/<int:pk>', views.MessageDetailView.as_view(), name='message-info'),
    path('messages/new/', views.MessageFormView.as_view(), name='message-form'),
    path('submit/', views.HopSubmitView.as_view(), name='hop-submit'),
    path('submit-candidates/', views.HopSubmitCandidatesView.as_view(), name='hop-candidates-submit'),
    path('hop-auth-test', views.HopAuthTestView.as_view(), name='hop-auth-test'),
    path('login-redirect/', views.LoginRedirectView.as_view(), name='login-redirect'),
    path('logout-redirect/', views.LogoutRedirectView.as_view(), name='logout-redirect'),
    path('get-csrf-token/', views.GetCSRFTokenView.as_view(), name='get-csrf-token') # for the frontend

]
