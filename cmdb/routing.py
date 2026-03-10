from django.urls import path
from . import consumers

websocket_urlpatterns = [
    path('ws/ssh/<int:id>/', consumers.SSHConsumer.as_asgi()),
]