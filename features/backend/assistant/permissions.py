# Sintergica CE extension: assistant access control.
#
# The rule that matters: every tool runs with the requesting user's own reach,
# never with a service account. "Reach" here means the projects where the user
# is an ACTIVE ProjectMember — the same set they can open in the UI. A public
# project the user has not joined is visible in Plane's project list but its
# work items are not readable, so it stays out.

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
    """Projects the user may actually read. Returned as a list so callers can
    reuse it across several queries without re-hitting the DB."""
    return list(
        ProjectMember.objects.filter(
            member=user,
            workspace__slug=slug,
            is_active=True,
            project__archived_at__isnull=True,
        ).values_list("project_id", flat=True)
    )


def forbidden(detail="You don't have the required permissions."):
    return Response({"error": detail}, status=status.HTTP_403_FORBIDDEN)


def allow_assistant(view_func):
    """Any active workspace member can use the assistant."""

    @wraps(view_func)
    def _wrapped_view(instance, request, *args, **kwargs):
        if is_workspace_member(request.user, kwargs["slug"]):
            return view_func(instance, request, *args, **kwargs)
        return forbidden()

    return _wrapped_view
