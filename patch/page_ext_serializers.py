# Sintergica CE extension: expose Pages on the public (X-API-Key) API.
# Response shape mirrors what plane-sdk's Page pydantic model expects
# (all fields optional, extra allowed), so the official MCP server works
# against Community Edition.

from rest_framework import serializers

from plane.db.models import Page


class PageAPISerializer(serializers.ModelSerializer):
    parent_id = serializers.UUIDField(source="parent", read_only=True, allow_null=True)
    projects = serializers.SerializerMethodField()
    owned_by = serializers.UUIDField(source="owned_by_id", read_only=True)
    workspace = serializers.UUIDField(source="workspace_id", read_only=True)
    # CE has no page collections; always null so the SDK model stays happy.
    collection_id = serializers.SerializerMethodField()
    page_collection_id = serializers.SerializerMethodField()

    class Meta:
        model = Page
        fields = [
            "id",
            "name",
            "description_stripped",
            "description_html",
            "created_at",
            "updated_at",
            "owned_by",
            "workspace",
            "projects",
            "access",
            "color",
            "is_locked",
            "is_global",
            "archived_at",
            "parent_id",
            "collection_id",
            "page_collection_id",
            "view_props",
            "logo_props",
            "external_id",
            "external_source",
        ]
        read_only_fields = fields

    def get_projects(self, obj):
        # Prefer prefetched relation to avoid N+1 when listing.
        return [str(p.id) for p in obj.projects.all()]

    def get_collection_id(self, obj):
        return None

    def get_page_collection_id(self, obj):
        return None


class PageAPIListSerializer(PageAPISerializer):
    """Lighter variant for list responses: omits the full HTML body."""

    class Meta(PageAPISerializer.Meta):
        fields = [f for f in PageAPISerializer.Meta.fields if f != "description_html"]
        read_only_fields = fields
