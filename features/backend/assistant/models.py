# Sintergica CE extension: conversational assistant.
#
# Three tables, purely additive — nothing in Plane's own schema is touched.
# A conversation belongs to one workspace and one user (its owner); messages
# are the raw transcript we replay into the model, including the tool turns;
# actions are write operations the model proposed and that a human must
# confirm before anything happens (phase 2 — the table exists from the start
# so the schema does not move later).

from django.conf import settings
from django.db import models

from plane.db.models.base import BaseModel


class Conversation(BaseModel):
    workspace = models.ForeignKey(
        "db.Workspace", on_delete=models.CASCADE, related_name="assistant_conversations"
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="assistant_conversations",
    )
    title = models.CharField(max_length=255, blank=True, default="")
    # Snapshot of what the conversation was started with. Kept per conversation
    # so changing the workspace default does not rewrite old history.
    provider = models.CharField(max_length=50, blank=True, default="")
    model = models.CharField(max_length=255, blank=True, default="")
    # Where the user was standing when they opened the panel:
    # {"project_id": ..., "work_item_id": ..., "cycle_id": ..., "view": ...}
    context = models.JSONField(blank=True, default=dict)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Assistant Conversation"
        verbose_name_plural = "Assistant Conversations"
        db_table = "assistant_conversations"
        ordering = ("-updated_at",)

    def __str__(self):
        return f"Conversation<{self.id}>"


class Message(BaseModel):
    ROLE_CHOICES = (
        ("user", "User"),
        ("assistant", "Assistant"),
        ("tool", "Tool"),
    )

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    content = models.TextField(blank=True, default="")
    # What the assistant asked to run (role=assistant), in OpenAI tool_calls shape.
    tool_calls = models.JSONField(null=True, blank=True)
    # Which call this row answers (role=tool).
    tool_call_id = models.CharField(max_length=255, null=True, blank=True)
    tool_name = models.CharField(max_length=100, null=True, blank=True)
    model = models.CharField(max_length=255, blank=True, default="")
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    # Explicit ordering: created_at ties are common because a whole tool round
    # trip is written inside the same request.
    sequence = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Assistant Message"
        verbose_name_plural = "Assistant Messages"
        db_table = "assistant_messages"
        ordering = ("sequence", "created_at")

    def __str__(self):
        return f"Message<{self.role}:{self.id}>"


class Action(BaseModel):
    """A write operation the model proposed. Never executed without a human
    clicking confirm — this is the boundary that keeps prompt injection coming
    from work item descriptions from turning into real changes."""

    STATUS_CHOICES = (
        ("pending", "Pending"),
        ("confirmed", "Confirmed"),
        ("rejected", "Rejected"),
        ("executed", "Executed"),
        ("failed", "Failed"),
    )

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="actions"
    )
    message = models.ForeignKey(
        Message, on_delete=models.CASCADE, related_name="actions", null=True, blank=True
    )
    tool_name = models.CharField(max_length=100)
    tool_call_id = models.CharField(max_length=255, blank=True, default="")
    arguments = models.JSONField(blank=True, default=dict)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    result = models.JSONField(null=True, blank=True)
    executed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Assistant Action"
        verbose_name_plural = "Assistant Actions"
        db_table = "assistant_actions"
        ordering = ("-created_at",)

    def __str__(self):
        return f"Action<{self.tool_name}:{self.status}>"
