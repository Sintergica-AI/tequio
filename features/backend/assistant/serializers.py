# Sintergica CE extension: assistant serializers.

from rest_framework import serializers

from plane.assistant.models import Action, Conversation, Message


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = [
            "id",
            "role",
            "content",
            "tool_name",
            "tool_calls",
            "sequence",
            "model",
            "input_tokens",
            "output_tokens",
            "created_at",
        ]
        read_only_fields = fields


class ConversationSerializer(serializers.ModelSerializer):
    message_count = serializers.IntegerField(read_only=True, required=False)

    class Meta:
        model = Conversation
        fields = [
            "id",
            "title",
            "provider",
            "model",
            "context",
            "archived_at",
            "message_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "provider", "created_at", "updated_at"]


class ConversationDetailSerializer(ConversationSerializer):
    messages = serializers.SerializerMethodField()

    class Meta(ConversationSerializer.Meta):
        fields = ConversationSerializer.Meta.fields + ["messages"]

    def get_messages(self, obj):
        # The tool transcript is machinery, not conversation: the panel only
        # renders what a person would recognise as a turn.
        rows = obj.messages.exclude(role="tool").exclude(
            role="assistant", content="", tool_calls__isnull=False
        )
        return MessageSerializer(rows, many=True).data


class ActionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Action
        fields = ["id", "tool_name", "arguments", "status", "result", "executed_at", "created_at"]
        read_only_fields = fields
