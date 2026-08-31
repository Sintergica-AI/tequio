# Sintergica CE extension: chat serializers.

from rest_framework import serializers

from plane.app.serializers.user import UserLiteSerializer
from plane.chat.models import Channel, ChatMessage


class ChannelSerializer(serializers.ModelSerializer):
    # Annotated by the view; absent (None) elsewhere.
    unread_count = serializers.IntegerField(read_only=True, required=False)
    last_message_at = serializers.DateTimeField(read_only=True, required=False)
    is_muted = serializers.BooleanField(read_only=True, required=False)

    class Meta:
        model = Channel
        fields = [
            "id",
            "workspace",
            "project",
            "name",
            "description",
            "is_general",
            "access",
            "archived_at",
            "unread_count",
            "last_message_at",
            "is_muted",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "workspace",
            "project",
            "is_general",
            "access",
            "created_by",
            "created_at",
            "updated_at",
        ]


class MessageSerializer(serializers.ModelSerializer):
    actor_detail = serializers.SerializerMethodField()
    reactions = serializers.SerializerMethodField()
    work_item_links = serializers.SerializerMethodField()
    # Annotated on list querysets; computed lazily otherwise.
    reply_count = serializers.SerializerMethodField()
    last_reply_at = serializers.SerializerMethodField()

    class Meta:
        model = ChatMessage
        fields = [
            "id",
            "channel",
            "parent",
            "actor",
            "actor_detail",
            "message_html",
            "message_json",
            "message_stripped",
            "edited_at",
            "is_removed",
            "reactions",
            "work_item_links",
            "reply_count",
            "last_reply_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_actor_detail(self, obj):
        # Same shape the rest of the app uses for people.
        return UserLiteSerializer(obj.actor).data

    def get_reactions(self, obj):
        # Raw rows; the frontend groups them and knows which are its own.
        return [
            {"reaction": r.reaction, "actor": str(r.actor_id)}
            for r in obj.reactions.all()
        ]

    def get_work_item_links(self, obj):
        links = []
        for link in obj.work_item_links.all():
            issue = link.issue
            links.append(
                {
                    "issue_id": str(issue.id),
                    "project_id": str(issue.project_id),
                    "identifier": issue.project.identifier,
                    "sequence_id": issue.sequence_id,
                    "name": issue.name,
                    "state_group": issue.state.group if issue.state_id else None,
                }
            )
        return links

    def get_reply_count(self, obj):
        annotated = getattr(obj, "reply_count_annotated", None)
        if annotated is not None:
            return annotated
        if obj.parent_id is not None:
            return 0
        return obj.replies.count()

    def get_last_reply_at(self, obj):
        annotated = getattr(obj, "last_reply_at_annotated", None)
        if annotated is not None:
            return annotated
        return None

    def to_representation(self, obj):
        data = super().to_representation(obj)
        # Tombstone: a deleted root that anchors a live thread keeps its slot
        # but exposes no content.
        if obj.is_removed:
            data["message_html"] = ""
            data["message_json"] = None
            data["message_stripped"] = ""
        return data
