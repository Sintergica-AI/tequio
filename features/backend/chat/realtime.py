# Sintergica CE extension: push chat events to the live server.
#
# The live server exposes POST <base>/broadcast (secret-key protected); it
# fans the payload out to every websocket client of the channel's document via
# its Redis extension. Best-effort by design: if the push fails the chat
# degrades to the REST catch-up the clients already do — so failures log a
# warning and never break the request/task.
#
# settings.LIVE_URL is None in this deployment (LIVE_BASE_URL unset), so the
# default is the compose-internal address, verified reachable from the api
# container: http://live:3000/live

import json
import logging
import os

import requests
from django.conf import settings

logger = logging.getLogger("plane.worker")

TIMEOUT_SECONDS = 3


def _live_base():
    return (
        os.environ.get("CHAT_LIVE_URL")
        or getattr(settings, "LIVE_URL", None)
        or "http://live:3000/live"
    ).rstrip("/")


def channel_document_name(channel_id):
    return f"chat:{channel_id}"


def workspace_document_name(workspace_id):
    """Workspace-wide badge document: every chat client subscribes to it and
    gets light channel.activity events for unread counters."""
    return f"chat:workspace:{workspace_id}"


def broadcast_channel_event(channel_id, payload):
    """POST the event to the live server. Returns True if delivered to the
    broadcaster (not necessarily to any client)."""
    secret = os.environ.get("LIVE_SERVER_SECRET_KEY", "")
    if not secret:
        logger.warning("chat.realtime: LIVE_SERVER_SECRET_KEY missing; skipping broadcast")
        return False
    try:
        response = requests.post(
            f"{_live_base()}/broadcast/",
            data=json.dumps(
                {"document_name": channel_document_name(channel_id), "payload": payload},
                default=str,
            ),
            headers={
                "Content-Type": "application/json",
                "live-server-secret-key": secret,
            },
            timeout=TIMEOUT_SECONDS,
        )
        if response.status_code != 200:
            logger.warning(
                "chat.realtime: broadcast returned %s for channel %s",
                response.status_code,
                channel_id,
            )
            return False
        return True
    except requests.RequestException as exc:
        logger.warning("chat.realtime: broadcast failed for channel %s: %s", channel_id, exc)
        return False
