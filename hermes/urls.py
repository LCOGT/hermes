from django.urls import path
from hermes import views

urlpatterns = [
    path('messages', views.MessageListView.as_view(), name='message-list'),
    path('messages/<int:pk>', views.MessageDetailView.as_view(), name='message-info'),
]
