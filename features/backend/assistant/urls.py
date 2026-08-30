# Sintergica CE extension: assistant URL routes. Mounted under /api/ from
# /code/plane/urls.py.

from django.urls import path

from plane.assistant.views import (
    AssistantConfigEndpoint,
    ConversationDetailEndpoint,
    ConversationMessagesEndpoint,
    ConversationsEndpoint,
)

urlpatterns = [
    path(
        "workspaces/<str:slug>/assistant/config/",
        AssistantConfigEndpoint.as_view(),
        name="assistant-config",
    ),
    path(
        "workspaces/<str:slug>/assistant/conversations/",
        ConversationsEndpoint.as_view(),
        name="assistant-conversations",
    ),
    path(
        "workspaces/<str:slug>/assistant/conversations/<uuid:pk>/",
        ConversationDetailEndpoint.as_view(),
        name="assistant-conversation-detail",
    ),
    path(
        "workspaces/<str:slug>/assistant/conversations/<uuid:pk>/messages/",
        ConversationMessagesEndpoint.as_view(),
        name="assistant-conversation-messages",
    ),
]
