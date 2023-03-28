from django.urls import path
from hermes import views

urlpatterns = [
    path('messages', views.MessageListView.as_view(), name='message-list'),
    path('messages/<int:pk>', views.MessageDetailView.as_view(), name='message-detail'),
    path('messages/new/', views.MessageFormView.as_view(), name='message-form'),
    path('login-redirect/', views.LoginRedirectView.as_view(), name='login-redirect'),
    path('logout-redirect/', views.LogoutRedirectView.as_view(), name='logout-redirect'),
    path('get-csrf-token/', views.GetCSRFTokenView.as_view(), name='get-csrf-token') # for the frontend
]
