# Sintergica CE extension: serializers for workspace-level (organization) wiki pages.
# Derived from plane/app/serializers/page.py (AGPL-3.0-only).

from plane.app.serializers.page import PageSerializer, PageDetailSerializer
from plane.db.models import Page, PageLabel, Workspace


class WorkspacePageSerializer(PageSerializer):
    """Create/update pages scoped to a workspace (is_global=True, no ProjectPage row)."""

    def create(self, validated_data):
        labels = validated_data.pop("labels", None)
        slug = self.context["slug"]
        owned_by_id = self.context["owned_by_id"]
        description_json = self.context.get("description_json", {})
        description_binary = self.context.get("description_binary", None)
        description_html = self.context.get("description_html", "<p></p>")

        workspace = Workspace.objects.get(slug=slug)

        page = Page.objects.create(
            **validated_data,
            description_json=description_json,
            description_binary=description_binary,
            description_html=description_html,
            owned_by_id=owned_by_id,
            workspace_id=workspace.id,
            is_global=True,
        )

        if labels is not None:
            PageLabel.objects.bulk_create(
                [
                    PageLabel(
                        label=label,
                        page=page,
                        workspace_id=page.workspace_id,
                        created_by_id=page.created_by_id,
                        updated_by_id=page.updated_by_id,
                    )
                    for label in labels
                ],
                batch_size=10,
            )
        return page


class WorkspacePageDetailSerializer(WorkspacePageSerializer):
    class Meta(PageSerializer.Meta):
        fields = PageSerializer.Meta.fields + ["description_html"]


__all__ = [
    "WorkspacePageSerializer",
    "WorkspacePageDetailSerializer",
    "PageDetailSerializer",
]
