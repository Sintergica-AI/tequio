# Sintergica CE extension: Pages / features / collections on the public API.
#
# Views authenticate with X-API-Key (same as the rest of /api/v1/) and reuse
# the internal Page model + background tasks so pages created here behave
# exactly like ones created from the web UI.

from django.db.models import Q
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response

from plane.api.views.base import BaseAPIView
from plane.app.views.page.base import unarchive_archive_page_and_descendants
from plane.bgtasks.page_transaction_task import page_transaction
from plane.db.models import Page, Project, ProjectMember, ProjectPage, Workspace, WorkspaceMember

from plane.api.serializers.page_ext import PageAPIListSerializer, PageAPISerializer

DEFAULT_HTML = "<p></p>"


def _visible_pages(user, slug):
    """Pages the requesting user may see: pages in projects where they are an
    active member, plus global (workspace-level) pages — own pages or public."""
    project_pages = Q(
        projects__project_projectmember__member=user,
        projects__project_projectmember__is_active=True,
        projects__archived_at__isnull=True,
    )
    global_pages = Q(is_global=True)
    return (
        Page.objects.filter(workspace__slug=slug)
        .filter(project_pages | global_pages)
        .filter(Q(owned_by=user) | Q(access=0))
        .filter(moved_to_page__isnull=True)
        .select_related("workspace", "owned_by")
        .prefetch_related("projects")
        .distinct()
    )


def _apply_archived_filter(request, qs):
    archived = request.GET.get("archived", "false").lower() in ("true", "1")
    return qs.filter(archived_at__isnull=False) if archived else qs.filter(archived_at__isnull=True)


def _is_project_member(user, slug, project_id):
    return ProjectMember.objects.filter(
        workspace__slug=slug, project_id=project_id, member=user, is_active=True
    ).exists()


def _create_page(request, slug, project_id=None):
    name = request.data.get("name")
    if not name:
        return None, Response({"error": "name is required"}, status=status.HTTP_400_BAD_REQUEST)

    workspace = Workspace.objects.get(slug=slug)
    description_html = request.data.get("description_html") or DEFAULT_HTML

    access = request.data.get("access", 0)
    try:
        access = int(access)
    except (TypeError, ValueError):
        access = 0

    page = Page.objects.create(
        workspace_id=workspace.id,
        name=name,
        description_html=description_html,
        owned_by_id=request.user.id,
        access=access,
        color=request.data.get("color") or "",
        is_locked=bool(request.data.get("is_locked", False)),
        parent_id=request.data.get("parent_id") or None,
        external_id=request.data.get("external_id") or None,
        external_source=request.data.get("external_source") or None,
        is_global=project_id is None,
        created_by_id=request.user.id,
        updated_by_id=request.user.id,
    )
    if project_id is not None:
        ProjectPage.objects.create(
            workspace_id=workspace.id,
            project_id=project_id,
            page_id=page.id,
            created_by_id=request.user.id,
            updated_by_id=request.user.id,
        )
    # Record the initial content transaction (mirrors the internal viewset).
    page_transaction.delay(
        new_description_html=description_html,
        old_description_html=None,
        page_id=str(page.id),
    )
    return page, None


def _update_page(request, page):
    if page.is_locked and str(request.data.get("is_locked", "")).lower() not in ("false", "0"):
        if "is_locked" not in request.data:
            return Response({"error": "Page is locked"}, status=status.HTTP_400_BAD_REQUEST)

    if "access" in request.data and page.owned_by_id != request.user.id:
        if int(request.data.get("access", page.access)) != page.access:
            return Response(
                {"error": "Access can only be changed by the page owner"},
                status=status.HTTP_400_BAD_REQUEST,
            )

    old_html = page.description_html
    updatable = {
        "name": "name",
        "access": "access",
        "color": "color",
        "is_locked": "is_locked",
        "external_id": "external_id",
        "external_source": "external_source",
        "view_props": "view_props",
        "logo_props": "logo_props",
    }
    for key, field in updatable.items():
        if key in request.data:
            setattr(page, field, request.data[key])
    if "parent_id" in request.data:
        page.parent_id = request.data.get("parent_id") or None
    new_html = request.data.get("description_html")
    if new_html is not None:
        page.description_html = new_html
    if "archived_at" in request.data:
        raw = request.data.get("archived_at")
        page.archived_at = raw or None
    page.updated_by_id = request.user.id
    page.save()

    if new_html is not None and new_html != old_html:
        page_transaction.delay(
            new_description_html=new_html,
            old_description_html=old_html,
            page_id=str(page.id),
        )
    return None


# ---------------------------------------------------------------------------
# Project-scoped pages
# ---------------------------------------------------------------------------


class ProjectPageAPIEndpoint(BaseAPIView):
    def get(self, request, slug, project_id, page_id=None):
        if not _is_project_member(request.user, slug, project_id):
            return Response({"error": "Not a member of this project"}, status=status.HTTP_403_FORBIDDEN)
        qs = _visible_pages(request.user, slug).filter(projects__id=project_id)
        if page_id:
            try:
                page = qs.get(pk=page_id)
            except Page.DoesNotExist:
                return Response({"error": "Page not found"}, status=status.HTTP_404_NOT_FOUND)
            return Response(PageAPISerializer(page).data, status=status.HTTP_200_OK)
        qs = _apply_archived_filter(request, qs).order_by("-created_at")
        return self.paginate(
            request=request,
            queryset=qs,
            on_results=lambda pages: PageAPIListSerializer(pages, many=True).data,
        )

    def post(self, request, slug, project_id):
        if not _is_project_member(request.user, slug, project_id):
            return Response({"error": "Not a member of this project"}, status=status.HTTP_403_FORBIDDEN)
        if not Project.objects.filter(pk=project_id, workspace__slug=slug, archived_at__isnull=True).exists():
            return Response({"error": "Project not found"}, status=status.HTTP_404_NOT_FOUND)
        page, err = _create_page(request, slug, project_id=project_id)
        if err:
            return err
        return Response(PageAPISerializer(page).data, status=status.HTTP_201_CREATED)

    def put(self, request, slug, project_id, page_id):
        return self._update(request, slug, project_id, page_id)

    def patch(self, request, slug, project_id, page_id):
        return self._update(request, slug, project_id, page_id)

    def _update(self, request, slug, project_id, page_id):
        if not _is_project_member(request.user, slug, project_id):
            return Response({"error": "Not a member of this project"}, status=status.HTTP_403_FORBIDDEN)
        try:
            page = _visible_pages(request.user, slug).filter(projects__id=project_id).get(pk=page_id)
        except Page.DoesNotExist:
            return Response({"error": "Page not found"}, status=status.HTTP_404_NOT_FOUND)
        err = _update_page(request, page)
        if err:
            return err
        page.refresh_from_db()
        return Response(PageAPISerializer(page).data, status=status.HTTP_200_OK)

    def delete(self, request, slug, project_id, page_id):
        if not _is_project_member(request.user, slug, project_id):
            return Response({"error": "Not a member of this project"}, status=status.HTTP_403_FORBIDDEN)
        try:
            page = Page.objects.get(pk=page_id, workspace__slug=slug, projects__id=project_id)
        except Page.DoesNotExist:
            return Response({"error": "Page not found"}, status=status.HTTP_404_NOT_FOUND)
        if page.owned_by_id != request.user.id and not ProjectMember.objects.filter(
            workspace__slug=slug, project_id=project_id, member=request.user, is_active=True, role=20
        ).exists():
            return Response(
                {"error": "Only the page owner or a project admin can delete a page"},
                status=status.HTTP_403_FORBIDDEN,
            )
        page.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProjectPageArchiveAPIEndpoint(BaseAPIView):
    def post(self, request, slug, project_id, page_id):
        return self._set_archived(request, slug, project_id, page_id, timezone.now())

    def delete(self, request, slug, project_id, page_id):
        return self._set_archived(request, slug, project_id, page_id, None)

    def _set_archived(self, request, slug, project_id, page_id, archived_at):
        if not _is_project_member(request.user, slug, project_id):
            return Response({"error": "Not a member of this project"}, status=status.HTTP_403_FORBIDDEN)
        try:
            page = Page.objects.get(pk=page_id, workspace__slug=slug, projects__id=project_id)
        except Page.DoesNotExist:
            return Response({"error": "Page not found"}, status=status.HTTP_404_NOT_FOUND)
        unarchive_archive_page_and_descendants(page_id, archived_at)
        return Response(
            {"archived_at": str(archived_at) if archived_at else None},
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# Workspace-scoped pages
# ---------------------------------------------------------------------------


class WorkspacePageAPIEndpoint(BaseAPIView):
    def _is_workspace_member(self, user, slug):
        return WorkspaceMember.objects.filter(workspace__slug=slug, member=user, is_active=True).exists()

    def get(self, request, slug, page_id=None):
        if not self._is_workspace_member(request.user, slug):
            return Response({"error": "Not a member of this workspace"}, status=status.HTTP_403_FORBIDDEN)
        qs = _visible_pages(request.user, slug)
        if page_id:
            try:
                page = qs.get(pk=page_id)
            except Page.DoesNotExist:
                return Response({"error": "Page not found"}, status=status.HTTP_404_NOT_FOUND)
            return Response(PageAPISerializer(page).data, status=status.HTTP_200_OK)
        qs = _apply_archived_filter(request, qs).order_by("-created_at")
        return self.paginate(
            request=request,
            queryset=qs,
            on_results=lambda pages: PageAPIListSerializer(pages, many=True).data,
        )

    def post(self, request, slug):
        if not self._is_workspace_member(request.user, slug):
            return Response({"error": "Not a member of this workspace"}, status=status.HTTP_403_FORBIDDEN)
        # CE has no workspace-level wiki UI; if a project_id is supplied we file
        # the page there so it is visible in the app. Otherwise it is stored as
        # a global page (accessible via API).
        project_id = request.data.get("project_id") or None
        if project_id and not _is_project_member(request.user, slug, project_id):
            return Response({"error": "Not a member of the target project"}, status=status.HTTP_403_FORBIDDEN)
        page, err = _create_page(request, slug, project_id=project_id)
        if err:
            return err
        return Response(PageAPISerializer(page).data, status=status.HTTP_201_CREATED)

    def put(self, request, slug, page_id):
        return self._update(request, slug, page_id)

    def patch(self, request, slug, page_id):
        return self._update(request, slug, page_id)

    def _update(self, request, slug, page_id):
        if not self._is_workspace_member(request.user, slug):
            return Response({"error": "Not a member of this workspace"}, status=status.HTTP_403_FORBIDDEN)
        try:
            page = _visible_pages(request.user, slug).get(pk=page_id)
        except Page.DoesNotExist:
            return Response({"error": "Page not found"}, status=status.HTTP_404_NOT_FOUND)
        err = _update_page(request, page)
        if err:
            return err
        page.refresh_from_db()
        return Response(PageAPISerializer(page).data, status=status.HTTP_200_OK)

    def delete(self, request, slug, page_id):
        if not self._is_workspace_member(request.user, slug):
            return Response({"error": "Not a member of this workspace"}, status=status.HTTP_403_FORBIDDEN)
        try:
            page = _visible_pages(request.user, slug).get(pk=page_id)
        except Page.DoesNotExist:
            return Response({"error": "Page not found"}, status=status.HTTP_404_NOT_FOUND)
        if page.owned_by_id != request.user.id and not WorkspaceMember.objects.filter(
            workspace__slug=slug, member=request.user, is_active=True, role=20
        ).exists():
            return Response(
                {"error": "Only the page owner or a workspace admin can delete a page"},
                status=status.HTTP_403_FORBIDDEN,
            )
        page.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class WorkspacePageArchiveAPIEndpoint(BaseAPIView):
    def post(self, request, slug, page_id):
        return self._set_archived(request, slug, page_id, timezone.now())

    def delete(self, request, slug, page_id):
        return self._set_archived(request, slug, page_id, None)

    def _set_archived(self, request, slug, page_id, archived_at):
        try:
            page = _visible_pages(request.user, slug).get(pk=page_id)
        except Page.DoesNotExist:
            return Response({"error": "Page not found"}, status=status.HTTP_404_NOT_FOUND)
        unarchive_archive_page_and_descendants(str(page.id), archived_at)
        return Response(
            {"archived_at": str(archived_at) if archived_at else None},
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# Features (SDK parity: GET/PATCH /features)
# ---------------------------------------------------------------------------

_PROJECT_FEATURE_MAP = {
    # SDK name -> CE Project model field
    "modules": "module_view",
    "cycles": "cycle_view",
    "views": "issue_views_view",
    "pages": "page_view",
    "intakes": "intake_view",
    "work_item_types": "is_issue_type_enabled",
    "time_tracking": "is_time_tracking_enabled",
}


class ProjectFeatureAPIEndpoint(BaseAPIView):
    def get(self, request, slug, project_id):
        if not _is_project_member(request.user, slug, project_id):
            return Response({"error": "Not a member of this project"}, status=status.HTTP_403_FORBIDDEN)
        try:
            project = Project.objects.get(pk=project_id, workspace__slug=slug)
        except Project.DoesNotExist:
            return Response({"error": "Project not found"}, status=status.HTTP_404_NOT_FOUND)
        data = {sdk: getattr(project, field) for sdk, field in _PROJECT_FEATURE_MAP.items()}
        # Commercial-only features: absent in CE, reported as disabled.
        data.update({"epics": False, "workflows": False, "parallel_cycles": False, "project_updates": False})
        return Response(data, status=status.HTTP_200_OK)

    def patch(self, request, slug, project_id):
        if not ProjectMember.objects.filter(
            workspace__slug=slug, project_id=project_id, member=request.user, is_active=True, role=20
        ).exists():
            return Response(
                {"error": "Only project admins can update features"}, status=status.HTTP_403_FORBIDDEN
            )
        try:
            project = Project.objects.get(pk=project_id, workspace__slug=slug)
        except Project.DoesNotExist:
            return Response({"error": "Project not found"}, status=status.HTTP_404_NOT_FOUND)
        unsupported = []
        for sdk_name, value in request.data.items():
            field = _PROJECT_FEATURE_MAP.get(sdk_name)
            if field is None:
                unsupported.append(sdk_name)
                continue
            setattr(project, field, bool(value))
        project.save()
        data = {sdk: getattr(project, field) for sdk, field in _PROJECT_FEATURE_MAP.items()}
        if unsupported:
            data["_note"] = (
                "Ignored features not available in Plane Community Edition: " + ", ".join(unsupported)
            )
        return Response(data, status=status.HTTP_200_OK)


class WorkspaceFeatureAPIEndpoint(BaseAPIView):
    def get(self, request, slug):
        if not WorkspaceMember.objects.filter(workspace__slug=slug, member=request.user, is_active=True).exists():
            return Response({"error": "Not a member of this workspace"}, status=status.HTTP_403_FORBIDDEN)
        # These are all commercial features; CE reports them disabled.
        return Response(
            {"project_grouping": False, "initiatives": False, "teams": False, "customers": False},
            status=status.HTTP_200_OK,
        )

    def patch(self, request, slug):
        return Response(
            {"error": "Workspace features (initiatives, teams, customers) require Plane Commercial and are not available in Community Edition"},
            status=status.HTTP_400_BAD_REQUEST,
        )


# ---------------------------------------------------------------------------
# Collections (not in the CE data model): graceful stubs
# ---------------------------------------------------------------------------

_EMPTY_PAGE = {
    "grouped_by": None,
    "sub_grouped_by": None,
    "total_count": 0,
    "next_cursor": "20:1:0",
    "prev_cursor": "20:-1:1",
    "next_page_results": False,
    "prev_page_results": False,
    "count": 0,
    "total_pages": 1,
    "total_results": 0,
    "extra_stats": None,
    "results": [],
}

_COLLECTIONS_MSG = (
    "Page collections require Plane Commercial and are not available in "
    "Community Edition. Pages can still be organised with parent/sub-pages."
)


class CollectionAPIEndpoint(BaseAPIView):
    def get(self, request, slug, collection_id=None, extra=None):
        if collection_id:
            return Response({"error": _COLLECTIONS_MSG}, status=status.HTTP_400_BAD_REQUEST)
        # plane-sdk expects a plain list here, not a paginated envelope.
        return Response([], status=status.HTTP_200_OK)

    def post(self, request, slug, collection_id=None, extra=None):
        return Response({"error": _COLLECTIONS_MSG}, status=status.HTTP_400_BAD_REQUEST)

    def patch(self, request, slug, collection_id=None, extra=None):
        return Response({"error": _COLLECTIONS_MSG}, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, slug, collection_id=None, extra=None):
        return Response({"error": _COLLECTIONS_MSG}, status=status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# Work-item pages (commercial concept): graceful stubs
# ---------------------------------------------------------------------------

_WI_PAGES_MSG = (
    "Attaching pages to work items requires Plane Commercial and is not "
    "available in Community Edition."
)


class WorkItemPageAPIEndpoint(BaseAPIView):
    def get(self, request, slug, project_id, work_item_id, page_id=None):
        if page_id:
            return Response({"error": _WI_PAGES_MSG}, status=status.HTTP_400_BAD_REQUEST)
        return Response(_EMPTY_PAGE, status=status.HTTP_200_OK)

    def post(self, request, slug, project_id, work_item_id, page_id=None):
        return Response({"error": _WI_PAGES_MSG}, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, slug, project_id, work_item_id, page_id=None):
        return Response({"error": _WI_PAGES_MSG}, status=status.HTTP_400_BAD_REQUEST)
