# Sintergica CE extension: chat URL routes. Mounted under /api/ from
# /code/plane/urls.py.

from django.urls import path

from plane.chat.views import (
    ChatChannelDetailEndpoint,
    ChatChannelMembershipEndpoint,
    ChatChannelsEndpoint,
    ChatMessageDetailEndpoint,
    ChatMessagesEndpoint,
    ChatReactionsEndpoint,
    ChatReadEndpoint,
    ChatThreadEndpoint,
    ChatUnreadsEndpoint,
    ChatWorkItemLinksEndpoint,
)

urlpatterns = [
    path(
        "workspaces/<str:slug>/chat/channels/",
        ChatChannelsEndpoint.as_view(),
        name="chat-channels",
    ),
    path(
        "workspaces/<str:slug>/chat/unreads/",
        ChatUnreadsEndpoint.as_view(),
        name="chat-unreads",
    ),
    path(
        "workspaces/<str:slug>/chat/channels/<uuid:channel_id>/",
        ChatChannelDetailEndpoint.as_view(),
        name="chat-channel-detail",
    ),
    path(
        "workspaces/<str:slug>/chat/channels/<uuid:channel_id>/membership/",
        ChatChannelMembershipEndpoint.as_view(),
        name="chat-channel-membership",
    ),
    path(
        "workspaces/<str:slug>/chat/channels/<uuid:channel_id>/read/",
        ChatReadEndpoint.as_view(),
        name="chat-channel-read",
    ),
    path(
        "workspaces/<str:slug>/chat/channels/<uuid:channel_id>/messages/",
        ChatMessagesEndpoint.as_view(),
        name="chat-messages",
    ),
    path(
        "workspaces/<str:slug>/chat/channels/<uuid:channel_id>/messages/<uuid:message_id>/",
        ChatMessageDetailEndpoint.as_view(),
        name="chat-message-detail",
    ),
    path(
        "workspaces/<str:slug>/chat/channels/<uuid:channel_id>/messages/<uuid:message_id>/thread/",
        ChatThreadEndpoint.as_view(),
        name="chat-message-thread",
    ),
    path(
        "workspaces/<str:slug>/chat/channels/<uuid:channel_id>/messages/<uuid:message_id>/reactions/",
        ChatReactionsEndpoint.as_view(),
        name="chat-message-reactions",
    ),
    path(
        "workspaces/<str:slug>/chat/channels/<uuid:channel_id>/messages/<uuid:message_id>/reactions/<str:reaction>/",
        ChatReactionsEndpoint.as_view(),
        name="chat-message-reaction-detail",
    ),
    path(
        "workspaces/<str:slug>/chat/channels/<uuid:channel_id>/messages/<uuid:message_id>/work-items/",
        ChatWorkItemLinksEndpoint.as_view(),
        name="chat-message-work-items",
    ),
    path(
        "workspaces/<str:slug>/chat/channels/<uuid:channel_id>/messages/<uuid:message_id>/work-items/<uuid:issue_id>/",
        ChatWorkItemLinksEndpoint.as_view(),
        name="chat-message-work-item-detail",
    ),
]
