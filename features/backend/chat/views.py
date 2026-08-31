# Sintergica CE extension: chat endpoints (session-authenticated app API).
#
# Every query goes through channel_queryset() so a channel outside the user's
# reach 404s instead of 403ing. Postgres is the source of truth; realtime
# events are pushed after commit by a celery task (phase 3) — the REST
# response never waits on the live server.

from django.db import IntegrityError
from django.db.models import Count, F, Max, OuterRef, Prefetch, Q, Subquery
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.html import strip_tags
from rest_framework import status
from rest_framework.response import Response

from plane.app.views.base import BaseAPIView
from plane.chat.models import (
    Channel,
    ChannelMember,
    ChatMessage,
    MessageReaction,
    MessageWorkItemLink,
)
from plane.chat.permissions import (
    MEMBER_ROLE,
    accessible_project_ids,
    allow_chat,
    workspace_role,
    channel_queryset,
    get_workspace,
    is_project_admin,
    is_workspace_admin,
)
from plane.chat.serializers import ChannelSerializer, MessageSerializer
from plane.chat.tasks import chat_event_task, chat_message_notify_task
from plane.db.models import Issue, ProjectMember

MAX_MESSAGE_CHARS = 20000
MESSAGES_PAGE_SIZE = 50
CATCHUP_CAP = 200
GENERAL_NAME = "general"


def _parse_ts(raw):
    """parse_datetime, tolerant of '+' arriving as a space: a '+00:00' offset
    in an unencoded query string decodes to ' 00:00' and would parse to None."""
    if not raw:
        return None
    return parse_datetime(raw.replace(" ", "+"))


def _bad_request(detail):
    return Response({"error": detail}, status=status.HTTP_400_BAD_REQUEST)


def _not_found():
    return Response({"error": "Not found."}, status=status.HTTP_404_NOT_FOUND)


def _get_channel(request, slug, channel_id):
    return channel_queryset(request.user, slug).filter(pk=channel_id).first()


def _live_messages(channel):
    """Base queryset with everything the serializer touches prefetched."""
    return (
        ChatMessage.objects.filter(channel=channel)
        .select_related("actor")
        .prefetch_related(
            "reactions",
            Prefetch(
                "work_item_links",
                queryset=MessageWorkItemLink.objects.select_related(
                    "issue__project", "issue__state"
                ),
            ),
        )
    )


def _annotate_thread_meta(qs):
    # The related-table join sees soft-deleted rows, so the filter is explicit.
    live_reply = Q(replies__deleted_at__isnull=True)
    return qs.annotate(
        reply_count_annotated=Count("replies", filter=live_reply),
        last_reply_at_annotated=Max("replies__created_at", filter=live_reply),
    )


def _parse_cursor(raw):
    """Cursor is '<created_at iso>,<uuid>' of the oldest message the client
    already has; we return strictly older rows."""
    try:
        ts_raw, _, id_raw = raw.partition(",")
        ts = _parse_ts(ts_raw)
        if ts is None or not id_raw:
            return None
        return ts, id_raw
    except Exception:
        return None


def _can_manage_channel(request, slug, channel):
    if is_workspace_admin(request.user, slug):
        return True
    if channel.project_id and is_project_admin(request.user, channel.project_id):
        return True
    return channel.created_by_id == request.user.id


class ChatChannelsEndpoint(BaseAPIView):
    @allow_chat
    def get(self, request, slug):
        qs = channel_queryset(request.user, slug)
        project_id = request.GET.get("project_id")
        if project_id:
            if project_id not in {
                str(pid) for pid in accessible_project_ids(request.user, slug)
            }:
                return _not_found()
            # First visit materializes the project's #general. get_or_create
            # instead of exists()+create so concurrent first visits collapse.
            workspace = get_workspace(slug)
            try:
                Channel.objects.get_or_create(
                    workspace=workspace,
                    project_id=project_id,
                    is_general=True,
                    defaults={"name": GENERAL_NAME},
                )
            except IntegrityError:
                pass
            qs = qs.filter(project_id=project_id)
        if request.GET.get("archived") != "true":
            qs = qs.filter(archived_at__isnull=True)

        member_rows = ChannelMember.objects.filter(
            channel=OuterRef("pk"), member=request.user
        )
        live_root = Q(
            messages__deleted_at__isnull=True,
            messages__parent__isnull=True,
            messages__is_removed=False,
        )
        qs = (
            qs.annotate(
                last_read=Subquery(member_rows.values("last_read_at")[:1]),
                is_muted=Subquery(member_rows.values("is_muted")[:1]),
            )
            .annotate(
                unread_count=Count(
                    "messages",
                    filter=live_root
                    & ~Q(messages__actor=request.user)
                    & (
                        Q(messages__created_at__gt=F("last_read"))
                        | Q(last_read__isnull=True)
                    ),
                ),
                last_message_at=Max(
                    "messages__created_at", filter=Q(messages__deleted_at__isnull=True)
                ),
            )
            .order_by("project_id", "name")
        )
        return Response(
            ChannelSerializer(qs, many=True).data, status=status.HTTP_200_OK
        )

    @allow_chat
    def post(self, request, slug):
        name = (request.data.get("name") or "").strip().lstrip("#")
        if not name:
            return _bad_request("Channel name is required.")
        if len(name) > 80:
            return _bad_request("Channel name is too long.")

        project_id = request.data.get("project_id") or None
        if project_id:
            # Creating inside a project requires member role there. A project
            # outside the user's reach 404s; a guest inside it gets a 403.
            role = (
                ProjectMember.objects.filter(
                    member=request.user,
                    project_id=project_id,
                    workspace__slug=slug,
                    is_active=True,
                    project__archived_at__isnull=True,
                )
                .values_list("role", flat=True)
                .first()
            )
            if role is None:
                return _not_found()
            if role < MEMBER_ROLE:
                return Response(
                    {"error": "Guests cannot create channels."},
                    status=status.HTTP_403_FORBIDDEN,
                )
        else:
            if (workspace_role(request.user, slug) or 0) < MEMBER_ROLE:
                return Response(
                    {"error": "Guests cannot create workspace channels."},
                    status=status.HTTP_403_FORBIDDEN,
                )

        workspace = get_workspace(slug)
        duplicate = Channel.objects.filter(
            workspace=workspace, project_id=project_id, name__iexact=name
        ).exists()
        if duplicate:
            return _bad_request("A channel with that name already exists.")
        try:
            channel = Channel.objects.create(
                workspace=workspace,
                project_id=project_id,
                name=name,
                description=(request.data.get("description") or "").strip(),
            )
        except IntegrityError:
            return _bad_request("A channel with that name already exists.")
        return Response(
            ChannelSerializer(channel).data, status=status.HTTP_201_CREATED
        )


class ChatChannelDetailEndpoint(BaseAPIView):
    @allow_chat
    def get(self, request, slug, channel_id):
        channel = _get_channel(request, slug, channel_id)
        if channel is None:
            return _not_found()
        return Response(ChannelSerializer(channel).data, status=status.HTTP_200_OK)

    @allow_chat
    def patch(self, request, slug, channel_id):
        channel = _get_channel(request, slug, channel_id)
        if channel is None:
            return _not_found()
        if not _can_manage_channel(request, slug, channel):
            return Response(
                {"error": "You cannot manage this channel."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if channel.is_general and (
            "name" in request.data or "archived_at" in request.data
        ):
            return _bad_request("The general channel cannot be renamed or archived.")
        if "name" in request.data:
            name = (request.data.get("name") or "").strip().lstrip("#")
            if not name:
                return _bad_request("Channel name is required.")
            if len(name) > 80:
                return _bad_request("Channel name is too long.")
            clash = (
                Channel.objects.filter(
                    workspace=channel.workspace,
                    project_id=channel.project_id,
                    name__iexact=name,
                )
                .exclude(pk=channel.pk)
                .exists()
            )
            if clash:
                return _bad_request("A channel with that name already exists.")
            channel.name = name
        if "description" in request.data:
            channel.description = (request.data.get("description") or "").strip()
        if "archived_at" in request.data:
            channel.archived_at = (
                timezone.now() if request.data.get("archived_at") else None
            )
        try:
            channel.save()
        except IntegrityError:
            return _bad_request("A channel with that name already exists.")
        return Response(ChannelSerializer(channel).data, status=status.HTTP_200_OK)

    @allow_chat
    def delete(self, request, slug, channel_id):
        channel = _get_channel(request, slug, channel_id)
        if channel is None:
            return _not_found()
        if not _can_manage_channel(request, slug, channel):
            return Response(
                {"error": "You cannot manage this channel."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if channel.is_general:
            return _bad_request("The general channel cannot be deleted.")
        channel.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ChatChannelMembershipEndpoint(BaseAPIView):
    """GET is intentionally an empty 200: the live server calls it with the
    user's cookie to decide whether to accept the websocket."""

    @allow_chat
    def get(self, request, slug, channel_id):
        channel = _get_channel(request, slug, channel_id)
        if channel is None:
            return _not_found()
        row = ChannelMember.objects.filter(
            channel=channel, member=request.user
        ).first()
        return Response(
            {
                "last_read_at": row.last_read_at if row else None,
                "is_muted": row.is_muted if row else False,
            },
            status=status.HTTP_200_OK,
        )

    @allow_chat
    def post(self, request, slug, channel_id):
        channel = _get_channel(request, slug, channel_id)
        if channel is None:
            return _not_found()
        row, _ = ChannelMember.objects.get_or_create(
            channel=channel,
            member=request.user,
            defaults={"workspace_id": channel.workspace_id},
        )
        if "is_muted" in request.data:
            row.is_muted = bool(request.data.get("is_muted"))
            row.save()
        return Response(
            {"last_read_at": row.last_read_at, "is_muted": row.is_muted},
            status=status.HTTP_200_OK,
        )


class ChatMessagesEndpoint(BaseAPIView):
    use_read_replica = False

    @allow_chat
    def get(self, request, slug, channel_id):
        channel = _get_channel(request, slug, channel_id)
        if channel is None:
            return _not_found()
        qs = _live_messages(channel)

        created_at__gt = request.GET.get("created_at__gt")
        if created_at__gt:
            # Catch-up after a reconnect: everything (roots AND replies) since
            # the newest message the client holds, oldest first.
            ts = _parse_ts(created_at__gt)
            if ts is None:
                return _bad_request("Invalid created_at__gt.")
            rows = list(
                _annotate_thread_meta(qs.filter(created_at__gt=ts)).order_by(
                    "created_at", "id"
                )[:CATCHUP_CAP]
            )
            return Response(
                {
                    "results": MessageSerializer(rows, many=True).data,
                    "has_more": len(rows) == CATCHUP_CAP,
                },
                status=status.HTTP_200_OK,
            )

        parent_id = request.GET.get("parent_id")
        if parent_id:
            rows = qs.filter(parent_id=parent_id).order_by("created_at", "id")
            return Response(
                {
                    "results": MessageSerializer(rows, many=True).data,
                    "has_more": False,
                },
                status=status.HTTP_200_OK,
            )

        # Default: newest page of root messages, keyset-paginated backwards.
        try:
            limit = min(int(request.GET.get("limit", MESSAGES_PAGE_SIZE)), 100)
        except (TypeError, ValueError):
            limit = MESSAGES_PAGE_SIZE
        qs = _annotate_thread_meta(qs.filter(parent__isnull=True))
        cursor_raw = request.GET.get("cursor")
        if cursor_raw:
            cursor = _parse_cursor(cursor_raw)
            if cursor is None:
                return _bad_request("Invalid cursor.")
            ts, row_id = cursor
            qs = qs.filter(
                Q(created_at__lt=ts) | Q(created_at=ts, id__lt=row_id)
            )
        rows = list(qs.order_by("-created_at", "-id")[: limit + 1])
        has_more = len(rows) > limit
        rows = rows[:limit]
        rows.reverse()  # oldest → newest, ready to render
        next_cursor = (
            f"{rows[0].created_at.isoformat()},{rows[0].id}" if rows and has_more else None
        )
        return Response(
            {
                "results": MessageSerializer(rows, many=True).data,
                "has_more": has_more,
                "next_cursor": next_cursor,
            },
            status=status.HTTP_200_OK,
        )

    @allow_chat
    def post(self, request, slug, channel_id):
        channel = _get_channel(request, slug, channel_id)
        if channel is None:
            return _not_found()
        if channel.archived_at is not None:
            return _bad_request("This channel is archived.")

        message_html = request.data.get("message_html") or ""
        if len(message_html) > MAX_MESSAGE_CHARS:
            return _bad_request("Message is too long.")
        linked_ids = request.data.get("linked_work_item_ids") or []
        if not strip_tags(message_html).strip() and not linked_ids:
            return _bad_request("Message is empty.")

        parent = None
        parent_id = request.data.get("parent_id")
        if parent_id:
            parent = (
                ChatMessage.objects.filter(channel=channel, pk=parent_id)
                .only("id", "parent_id")
                .first()
            )
            if parent is None:
                return _bad_request("Parent message not found.")
            # Threads are one level deep: replies to a reply hang off the root.
            if parent.parent_id is not None:
                parent = ChatMessage.objects.get(pk=parent.parent_id)

        message = ChatMessage.objects.create(
            channel=channel,
            workspace_id=channel.workspace_id,
            project_id=channel.project_id,
            actor=request.user,
            parent=parent,
            message_html=message_html,
            message_json=request.data.get("message_json"),
        )

        if linked_ids:
            allowed = set(accessible_project_ids(request.user, slug))
            issues = Issue.objects.filter(
                pk__in=linked_ids,
                workspace_id=channel.workspace_id,
                project_id__in=allowed,
            )
            MessageWorkItemLink.objects.bulk_create(
                [
                    MessageWorkItemLink(
                        message=message,
                        issue=issue,
                        workspace_id=channel.workspace_id,
                        created_by=request.user,
                    )
                    for issue in issues
                ]
            )

        chat_message_notify_task.delay(str(message.id), None)
        chat_event_task.delay(
            {"event": "message.new", "channel_id": str(channel.id), "message_id": str(message.id)}
        )

        row = (
            _annotate_thread_meta(_live_messages(channel)).filter(pk=message.pk).first()
        )
        return Response(MessageSerializer(row).data, status=status.HTTP_201_CREATED)


class ChatMessageDetailEndpoint(BaseAPIView):
    use_read_replica = False

    @allow_chat
    def patch(self, request, slug, channel_id, message_id):
        channel = _get_channel(request, slug, channel_id)
        if channel is None:
            return _not_found()
        message = ChatMessage.objects.filter(channel=channel, pk=message_id).first()
        if message is None or message.is_removed:
            return _not_found()
        if message.actor_id != request.user.id:
            return Response(
                {"error": "Only the author can edit a message."},
                status=status.HTTP_403_FORBIDDEN,
            )
        message_html = request.data.get("message_html") or ""
        if not strip_tags(message_html).strip():
            return _bad_request("Message is empty.")
        if len(message_html) > MAX_MESSAGE_CHARS:
            return _bad_request("Message is too long.")
        old_html = message.message_html
        message.message_html = message_html
        message.message_json = request.data.get("message_json")
        message.edited_at = timezone.now()
        message.save()
        # Only people newly mentioned by the edit get notified.
        chat_message_notify_task.delay(str(message.id), old_html)
        chat_event_task.delay(
            {"event": "message.updated", "channel_id": str(channel.id), "message_id": str(message.id)}
        )
        row = (
            _annotate_thread_meta(_live_messages(channel)).filter(pk=message.pk).first()
        )
        return Response(MessageSerializer(row).data, status=status.HTTP_200_OK)

    @allow_chat
    def delete(self, request, slug, channel_id, message_id):
        channel = _get_channel(request, slug, channel_id)
        if channel is None:
            return _not_found()
        message = ChatMessage.objects.filter(channel=channel, pk=message_id).first()
        if message is None:
            return _not_found()
        allowed = (
            message.actor_id == request.user.id
            or is_workspace_admin(request.user, slug)
            or (
                channel.project_id
                and is_project_admin(request.user, channel.project_id)
            )
        )
        if not allowed:
            return Response(
                {"error": "You cannot delete this message."},
                status=status.HTTP_403_FORBIDDEN,
            )
        has_live_replies = (
            message.parent_id is None and message.replies.exists()
        )
        if has_live_replies:
            # Tombstone: the thread keeps its anchor, the content goes away.
            message.message_html = ""
            message.message_json = None
            message.is_removed = True
            message.save()
            chat_event_task.delay(
                {"event": "message.updated", "channel_id": str(channel.id), "message_id": str(message.id)}
            )
        else:
            parent_id = str(message.parent_id) if message.parent_id else None
            message.delete()
            chat_event_task.delay(
                {
                    "event": "message.deleted",
                    "channel_id": str(channel.id),
                    "message_id": str(message_id),
                    "parent_id": parent_id,
                    "actor_id": str(request.user.id),
                }
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


class ChatThreadEndpoint(BaseAPIView):
    @allow_chat
    def get(self, request, slug, channel_id, message_id):
        channel = _get_channel(request, slug, channel_id)
        if channel is None:
            return _not_found()
        root = (
            _annotate_thread_meta(_live_messages(channel))
            .filter(pk=message_id, parent__isnull=True)
            .first()
        )
        if root is None:
            return _not_found()
        replies = (
            _live_messages(channel).filter(parent=root).order_by("created_at", "id")
        )
        return Response(
            {
                "root": MessageSerializer(root).data,
                "replies": MessageSerializer(replies, many=True).data,
            },
            status=status.HTTP_200_OK,
        )


class ChatReactionsEndpoint(BaseAPIView):
    use_read_replica = False

    @allow_chat
    def post(self, request, slug, channel_id, message_id):
        channel = _get_channel(request, slug, channel_id)
        if channel is None:
            return _not_found()
        message = ChatMessage.objects.filter(channel=channel, pk=message_id).first()
        if message is None or message.is_removed:
            return _not_found()
        reaction = (request.data.get("reaction") or "").strip()
        if not reaction or len(reaction) > 20:
            return _bad_request("Invalid reaction.")
        try:
            MessageReaction.objects.get_or_create(
                message=message,
                actor=request.user,
                reaction=reaction,
                defaults={"workspace_id": channel.workspace_id},
            )
        except IntegrityError:
            pass
        chat_event_task.delay(
            {
                "event": "reaction.added",
                "channel_id": str(channel.id),
                "message_id": str(message.id),
                "actor_id": str(request.user.id),
                "reaction": reaction,
            }
        )
        return Response({"reaction": reaction}, status=status.HTTP_200_OK)

    @allow_chat
    def delete(self, request, slug, channel_id, message_id, reaction):
        channel = _get_channel(request, slug, channel_id)
        if channel is None:
            return _not_found()
        row = MessageReaction.objects.filter(
            message__channel=channel,
            message_id=message_id,
            actor=request.user,
            reaction=reaction,
        ).first()
        if row is None:
            return _not_found()
        row.delete()
        chat_event_task.delay(
            {
                "event": "reaction.removed",
                "channel_id": str(channel.id),
                "message_id": str(message_id),
                "actor_id": str(request.user.id),
                "reaction": reaction,
            }
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class ChatReadEndpoint(BaseAPIView):
    use_read_replica = False

    @allow_chat
    def post(self, request, slug, channel_id):
        channel = _get_channel(request, slug, channel_id)
        if channel is None:
            return _not_found()
        provided = _parse_ts(request.data.get("last_read_at") or "")
        stamp = provided or timezone.now()
        row, _ = ChannelMember.objects.get_or_create(
            channel=channel,
            member=request.user,
            defaults={"workspace_id": channel.workspace_id},
        )
        # Monotonic: a stale tab can never move the marker backwards.
        if row.last_read_at is None or stamp > row.last_read_at:
            row.last_read_at = stamp
            row.save()
        return Response({"last_read_at": row.last_read_at}, status=status.HTTP_200_OK)


class ChatUnreadsEndpoint(BaseAPIView):
    @allow_chat
    def get(self, request, slug):
        member_rows = ChannelMember.objects.filter(
            channel=OuterRef("pk"), member=request.user
        )
        live_root = Q(
            messages__deleted_at__isnull=True,
            messages__parent__isnull=True,
            messages__is_removed=False,
        )
        qs = (
            channel_queryset(request.user, slug)
            .filter(archived_at__isnull=True)
            .annotate(last_read=Subquery(member_rows.values("last_read_at")[:1]))
            .annotate(
                unread_count=Count(
                    "messages",
                    filter=live_root
                    & ~Q(messages__actor=request.user)
                    & (
                        Q(messages__created_at__gt=F("last_read"))
                        | Q(last_read__isnull=True)
                    ),
                ),
                last_message_at=Max(
                    "messages__created_at", filter=Q(messages__deleted_at__isnull=True)
                ),
            )
            .values("id", "unread_count", "last_message_at")
        )
        return Response(
            [
                {
                    "channel_id": str(row["id"]),
                    "unread_count": row["unread_count"],
                    "last_message_at": row["last_message_at"],
                }
                for row in qs
            ],
            status=status.HTTP_200_OK,
        )


class ChatWorkItemLinksEndpoint(BaseAPIView):
    use_read_replica = False

    @allow_chat
    def post(self, request, slug, channel_id, message_id):
        channel = _get_channel(request, slug, channel_id)
        if channel is None:
            return _not_found()
        message = ChatMessage.objects.filter(channel=channel, pk=message_id).first()
        if message is None or message.is_removed:
            return _not_found()
        issue_id = request.data.get("issue_id")
        issue = Issue.objects.filter(
            pk=issue_id,
            workspace_id=channel.workspace_id,
            project_id__in=accessible_project_ids(request.user, slug),
        ).first()
        if issue is None:
            return _not_found()
        try:
            MessageWorkItemLink.objects.get_or_create(
                message=message,
                issue=issue,
                defaults={"workspace_id": channel.workspace_id},
            )
        except IntegrityError:
            pass
        row = _annotate_thread_meta(_live_messages(channel)).filter(pk=message.pk).first()
        return Response(MessageSerializer(row).data, status=status.HTTP_200_OK)

    @allow_chat
    def delete(self, request, slug, channel_id, message_id, issue_id):
        channel = _get_channel(request, slug, channel_id)
        if channel is None:
            return _not_found()
        link = MessageWorkItemLink.objects.filter(
            message__channel=channel, message_id=message_id, issue_id=issue_id
        ).first()
        if link is None:
            return _not_found()
        link.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
