# Sintergica CE extension: chat background work.
#
# Mention parsing is copied-adapted from plane.bgtasks.notification_task
# (upstream stays untouched). Celery discovers this module through
# INSTALLED_APPS autodiscovery — no worker config change needed.
#
# Phase 3 adds the realtime broadcast to this same task, so the REST response
# never waits on the live server.

from bs4 import BeautifulSoup
from celery import shared_task

from plane.db.models import Notification
from plane.chat.realtime import broadcast_channel_event


def extract_mentions(html):
    """User ids referenced as <mention-component entity_name="user_mention">
    inside the TipTap HTML. Same markup the issue-comment editor produces."""
    try:
        soup = BeautifulSoup(html or "", "html.parser")
        tags = soup.find_all("mention-component", attrs={"entity_name": "user_mention"})
        return list({tag["entity_identifier"] for tag in tags})
    except Exception:
        return []


def new_mentions(new_html, old_html):
    newer = extract_mentions(new_html)
    if old_html is None:
        return newer
    older = set(extract_mentions(old_html))
    return [m for m in newer if m not in older]


@shared_task
def chat_message_notify_task(message_id, old_html):
    """Notify people newly mentioned in a chat message. old_html is None on
    create; on edit it holds the previous HTML so only fresh mentions fire."""
    from plane.chat.models import ChatMessage
    from plane.chat.permissions import visible_channels_q
    from plane.db.models import ProjectMember, WorkspaceMember

    message = (
        ChatMessage.objects.filter(pk=message_id)
        .select_related("channel", "actor", "workspace")
        .first()
    )
    if message is None or message.is_removed:
        return

    mention_ids = new_mentions(message.message_html, old_html)
    mention_ids = [m for m in mention_ids if str(m) != str(message.actor_id)]
    if not mention_ids:
        return

    channel = message.channel

    # Only people who can actually open the channel get notified: active
    # workspace members, and for project channels, active project members.
    allowed = set(
        str(u)
        for u in WorkspaceMember.objects.filter(
            workspace_id=message.workspace_id,
            member_id__in=mention_ids,
            is_active=True,
        ).values_list("member_id", flat=True)
    )
    if channel.project_id:
        allowed &= set(
            str(u)
            for u in ProjectMember.objects.filter(
                project_id=channel.project_id,
                member_id__in=mention_ids,
                is_active=True,
            ).values_list("member_id", flat=True)
        )

    snippet = (message.message_stripped or "")[:120]
    rows = [
        Notification(
            workspace_id=message.workspace_id,
            project_id=message.project_id,
            sender="in_app:chat:mentioned",
            triggered_by_id=message.actor_id,
            receiver_id=receiver_id,
            entity_identifier=message.id,
            entity_name="chat_message",
            title=snippet,
            data={
                "channel": {
                    "id": str(channel.id),
                    "name": channel.name,
                    "project_id": str(channel.project_id) if channel.project_id else None,
                },
                "message": {
                    "id": str(message.id),
                    "parent_id": str(message.parent_id) if message.parent_id else None,
                    "snippet": snippet,
                },
            },
        )
        for receiver_id in allowed
    ]
    if rows:
        Notification.objects.bulk_create(rows, batch_size=100)


@shared_task
def chat_event_task(event):
    """Fan a chat event out to connected clients via the live server.

    For message.new / message.updated the payload carries the message fully
    serialized (same shape as REST) so clients render without a re-fetch.
    A tombstoned deletion arrives as message.updated (the row still exists,
    wiped); a real deletion as message.deleted.
    """
    from django.utils import timezone

    from plane.chat.models import ChatMessage
    from plane.chat.serializers import MessageSerializer

    kind = event.get("event")
    channel_id = event.get("channel_id")
    payload = {
        "event": kind,
        "channel_id": str(channel_id),
        "message_id": str(event.get("message_id")),
        "parent_id": str(event["parent_id"]) if event.get("parent_id") else None,
        "actor_id": str(event.get("actor_id")) if event.get("actor_id") else None,
        "ts": timezone.now().isoformat(),
    }
    if kind in ("message.new", "message.updated"):
        message = (
            ChatMessage.objects.filter(pk=event.get("message_id"))
            .select_related("actor")
            .prefetch_related("reactions", "work_item_links__issue__project", "work_item_links__issue__state")
            .first()
        )
        if message is None:
            return
        payload["parent_id"] = str(message.parent_id) if message.parent_id else None
        payload["actor_id"] = str(message.actor_id)
        payload["message"] = MessageSerializer(message).data
    if kind in ("reaction.added", "reaction.removed"):
        payload["reaction"] = event.get("reaction")
    broadcast_channel_event(str(channel_id), payload)
