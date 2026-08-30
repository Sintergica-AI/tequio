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
    pending_actions = serializers.SerializerMethodField()

    class Meta(ConversationSerializer.Meta):
        fields = ConversationSerializer.Meta.fields + ["messages", "pending_actions"]

    def get_pending_actions(self, obj):
        # Al reabrir una conversación el botón de confirmar tiene que seguir ahí:
        # una propuesta sin decidir no caduca por recargar la página.
        return ActionSerializer(obj.actions.filter(status="pending"), many=True).data

    def get_messages(self, obj):
        # The tool transcript is machinery, not conversation: the panel only
        # renders what a person would recognise as a turn.
        rows = obj.messages.exclude(role="tool").exclude(
            role="assistant", content="", tool_calls__isnull=False
        )
        return MessageSerializer(rows, many=True).data


class ActionSerializer(serializers.ModelSerializer):
    # Mientras está pendiente, `result` guarda el texto del botón. Se expone
    # aparte para que el panel no tenga que saber ese detalle.
    label = serializers.SerializerMethodField()
    detail = serializers.SerializerMethodField()

    class Meta:
        model = Action
        fields = [
            "id",
            "tool_name",
            "arguments",
            "status",
            "label",
            "detail",
            "result",
            "executed_at",
            "created_at",
        ]
        read_only_fields = fields

    def get_label(self, obj):
        return (obj.result or {}).get("label") or obj.tool_name

    def get_detail(self, obj):
        return (obj.result or {}).get("detail") or "" 
