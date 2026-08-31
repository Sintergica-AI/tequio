# Sintergica CE extension: chat access control.
#
# Membership is implicit: a channel with project=NULL is visible to every
# active workspace member; a project channel is visible to any active
# member of that project (guests included — chat is communication) — the same set of projects the user can open in the
# UI. ChannelMember is per-user state, never authorization.

from functools import wraps

from rest_framework import status
from rest_framework.response import Response

from plane.db.models import ProjectMember, Workspace, WorkspaceMember

ADMIN_ROLE = 20
MEMBER_ROLE = 15
GUEST_ROLE = 5


def workspace_role(user, slug):
    """Active workspace role, or None if not a member."""
    return (
        WorkspaceMember.objects.filter(member=user, workspace__slug=slug, is_active=True)
        .values_list("role", flat=True)
        .first()
    )


def is_workspace_member(user, slug):
    return workspace_role(user, slug) is not None


def is_workspace_admin(user, slug):
    return workspace_role(user, slug) == ADMIN_ROLE


def get_workspace(slug):
    return Workspace.objects.filter(slug=slug).first()


def accessible_project_ids(user, slug):
    """Projects the user may actually read (active membership, project not
    archived). Returned as a list so callers can reuse it across queries."""
    return list(
        ProjectMember.objects.filter(
            member=user,
            workspace__slug=slug,
            is_active=True,
            project__archived_at__isnull=True,
        ).values_list("project_id", flat=True)
    )


def is_project_admin(user, project_id):
    return ProjectMember.objects.filter(
        member=user, project_id=project_id, is_active=True, role=ADMIN_ROLE
    ).exists()


def visible_channels_q(project_ids):
    """Q for channels the user can see given their accessible projects."""
    from django.db.models import Q

    return Q(project__isnull=True) | Q(project_id__in=project_ids)


def channel_queryset(user, slug):
    """Channels the user can see in this workspace: every workspace-level
    channel plus the channels of projects within reach. Filtering through this
    everywhere means an inaccessible channel 404s instead of 403ing — no
    existence leak."""
    from plane.chat.models import Channel

    return Channel.objects.filter(workspace__slug=slug).filter(
        visible_channels_q(accessible_project_ids(user, slug))
    )


def forbidden(detail="You don't have the required permissions."):
    return Response({"error": detail}, status=status.HTTP_403_FORBIDDEN)


def allow_chat(view_func):
    """Any active workspace member can use chat."""

    @wraps(view_func)
    def _wrapped_view(instance, request, *args, **kwargs):
        if is_workspace_member(request.user, kwargs["slug"]):
            return view_func(instance, request, *args, **kwargs)
        return forbidden()

    return _wrapped_view
