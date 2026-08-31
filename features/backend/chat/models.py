# Sintergica CE extension: chat channels (ClickUp-style).
#
# Five tables, purely additive — nothing in Plane's own schema is touched.
# A channel belongs to a workspace and optionally to a project (project NULL =
# workspace-level channel). Membership is implicit: whoever can see the
# workspace/project can see its channels. ChannelMember only stores per-user
# state (last_read_at, mute) and is created lazily. Postgres is the source of
# truth for messages; the live server only pushes ephemeral events.

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils.html import strip_tags

from plane.db.models.base import BaseModel


class Channel(BaseModel):
    workspace = models.ForeignKey(
        "db.Workspace", on_delete=models.CASCADE, related_name="chat_channels"
    )
    # NULL project = workspace-level channel (e.g. #anuncios).
    project = models.ForeignKey(
        "db.Project",
        on_delete=models.CASCADE,
        related_name="chat_channels",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=255, blank=True, default="")
    description = models.TextField(blank=True, default="")
    # The auto-created #general of a project: cannot be renamed or deleted.
    is_general = models.BooleanField(default=False)
    # 0 = public (everyone with reach); 1 = private (explicit ChannelMember
    # rows are the authorization). DMs are always access=1.
    access = models.PositiveSmallIntegerField(default=0)
    # Direct message conversation (1:1 or group). No name; the client renders
    # the other members' names. Member set is immutable after creation.
    is_direct = models.BooleanField(default=False)
    # Canonical identity of a DM: sha256 of the sorted member ids, so opening
    # a DM with the same people always lands on the same channel.
    dm_key = models.CharField(max_length=64, null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Chat Channel"
        verbose_name_plural = "Chat Channels"
        db_table = "chat_channels"
        ordering = ("name",)
        indexes = [
            models.Index(fields=["workspace", "project"], name="chat_channel_scope_idx"),
        ]
        constraints = [
            # Names are unique case-insensitively within their scope. Project
            # NULLs are distinct in Postgres, so workspace-level channels need
            # their own constraint.
            models.UniqueConstraint(
                Lower("name"),
                "workspace",
                "project",
                condition=Q(deleted_at__isnull=True, project__isnull=False),
                name="chat_channel_project_name_uq",
            ),
            models.UniqueConstraint(
                Lower("name"),
                "workspace",
                # is_direct excluded: every DM has name "" and project NULL,
                # so the SECOND DM in a workspace would violate this (bit us
                # in production the moment a real DM already existed).
                condition=Q(deleted_at__isnull=True, project__isnull=True, is_direct=False),
                name="chat_channel_workspace_name_uq",
            ),
            models.UniqueConstraint(
                fields=["project"],
                condition=Q(is_general=True, deleted_at__isnull=True),
                name="chat_channel_general_uq",
            ),
            models.UniqueConstraint(
                fields=["workspace", "dm_key"],
                condition=Q(deleted_at__isnull=True, dm_key__isnull=False),
                name="chat_channel_dm_key_uq",
            ),
        ]

    def __str__(self):
        return f"Channel<{self.name}>"


class ChannelMember(BaseModel):
    """Per-user state on a channel — NOT authorization. Created lazily the
    first time the user marks the channel read or mutes it."""

    channel = models.ForeignKey(
        Channel, on_delete=models.CASCADE, related_name="members"
    )
    member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chat_channel_memberships",
    )
    workspace = models.ForeignKey(
        "db.Workspace", on_delete=models.CASCADE, related_name="chat_channel_members"
    )
    last_read_at = models.DateTimeField(null=True, blank=True)
    is_muted = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Chat Channel Member"
        verbose_name_plural = "Chat Channel Members"
        db_table = "chat_channel_members"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["channel", "member"],
                condition=Q(deleted_at__isnull=True),
                name="chat_channel_member_uq",
            ),
        ]

    def __str__(self):
        return f"ChannelMember<{self.channel_id}:{self.member_id}>"


class ChatMessage(BaseModel):
    channel = models.ForeignKey(
        Channel, on_delete=models.CASCADE, related_name="messages"
    )
    # Denormalized for cheap scoping queries (unreads, notifications).
    workspace = models.ForeignKey(
        "db.Workspace", on_delete=models.CASCADE, related_name="chat_messages"
    )
    project = models.ForeignKey(
        "db.Project",
        on_delete=models.CASCADE,
        related_name="chat_messages",
        null=True,
        blank=True,
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chat_messages",
    )
    # Threads are one level deep (Slack-style): parent always points at the
    # root message. The view normalizes parent.parent -> root on write.
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        related_name="replies",
        null=True,
        blank=True,
    )
    message_html = models.TextField(blank=True, default="<p></p>")
    message_json = models.JSONField(null=True, blank=True)
    message_stripped = models.TextField(blank=True, null=True)
    edited_at = models.DateTimeField(null=True, blank=True)
    # A root message that had replies when its author deleted it: the content
    # is wiped and this flag set, so the thread keeps its anchor (tombstone).
    is_removed = models.BooleanField(default=False)
    # Pinned messages (any channel member can pin/unpin).
    pinned_at = models.DateTimeField(null=True, blank=True)
    pinned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="chat_pinned_messages",
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "Chat Message"
        verbose_name_plural = "Chat Messages"
        db_table = "chat_messages"
        # created_at ties are broken by id so keyset pagination is total.
        ordering = ("created_at", "id")
        indexes = [
            models.Index(
                fields=["channel", "created_at"],
                condition=Q(deleted_at__isnull=True),
                name="chat_message_channel_ts_idx",
            ),
            models.Index(fields=["parent"], name="chat_message_parent_idx"),
        ]

    def save(self, *args, **kwargs):
        self.message_stripped = (
            strip_tags(self.message_html) if self.message_html != "" else ""
        )
        super().save(*args, **kwargs)

    def __str__(self):
        return f"ChatMessage<{self.id}>"


class MessageReaction(BaseModel):
    message = models.ForeignKey(
        ChatMessage, on_delete=models.CASCADE, related_name="reactions"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chat_message_reactions",
    )
    workspace = models.ForeignKey(
        "db.Workspace", on_delete=models.CASCADE, related_name="chat_message_reactions"
    )
    reaction = models.CharField(max_length=20)

    class Meta:
        verbose_name = "Chat Message Reaction"
        verbose_name_plural = "Chat Message Reactions"
        db_table = "chat_message_reactions"
        ordering = ("created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["message", "actor", "reaction"],
                condition=Q(deleted_at__isnull=True),
                name="chat_message_reaction_uq",
            ),
        ]

    def __str__(self):
        return f"MessageReaction<{self.reaction}>"


class MessageWorkItemLink(BaseModel):
    """A work item referenced from a chat message — rendered as a chip under
    the bubble. Who linked it = created_by from BaseModel."""

    message = models.ForeignKey(
        ChatMessage, on_delete=models.CASCADE, related_name="work_item_links"
    )
    issue = models.ForeignKey(
        "db.Issue", on_delete=models.CASCADE, related_name="chat_message_links"
    )
    workspace = models.ForeignKey(
        "db.Workspace", on_delete=models.CASCADE, related_name="chat_work_item_links"
    )

    class Meta:
        verbose_name = "Chat Message Work Item Link"
        verbose_name_plural = "Chat Message Work Item Links"
        db_table = "chat_message_work_items"
        ordering = ("created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["message", "issue"],
                condition=Q(deleted_at__isnull=True),
                name="chat_message_work_item_uq",
            ),
        ]

    def __str__(self):
        return f"MessageWorkItemLink<{self.message_id}:{self.issue_id}>"
