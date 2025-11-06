from django.urls import path
from hermes import views

urlpatterns = [
    path('login-redirect/', views.LoginRedirectView.as_view(), name='login-redirect'),
    path('logout-redirect/', views.LogoutRedirectView.as_view(), name='logout-redirect'),
    path('get-csrf-token/', views.GetCSRFTokenView.as_view(), name='get-csrf-token')  # for the frontend
]
