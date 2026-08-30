# Sintergica CE extension: finance access control.
# Finance access = active workspace ADMIN (role 20) OR a row in FinanceAccess
# (combined with an active workspace membership). Mirrors the decorator style
# of plane/app/permissions/base.py::allow_permission (AGPL-3.0-only).

from functools import wraps

from rest_framework import status
from rest_framework.response import Response

from plane.db.models import WorkspaceMember
from plane.finance.models import FinanceAccess

ADMIN_ROLE = 20


def is_workspace_admin(user, slug):
    return WorkspaceMember.objects.filter(
        member=user, workspace__slug=slug, role=ADMIN_ROLE, is_active=True
    ).exists()


def finance_role(user, slug):
    """"admin", "finance", "collections" or None."""
    if is_workspace_admin(user, slug):
        return "admin"
    if not WorkspaceMember.objects.filter(member=user, workspace__slug=slug, is_active=True).exists():
        return None
    row = FinanceAccess.objects.filter(member=user, workspace__slug=slug).first()
    return row.role if row else None


def has_finance_access(user, slug):
    """Full access: admins and the "finance" role."""
    return finance_role(user, slug) in ("admin", "finance")


def has_collections_access(user, slug):
    """Cobranza scope: pending charges + recording payments. Any finance role
    qualifies — full access is a superset of collections."""
    return finance_role(user, slug) is not None


def _forbidden():
    return Response(
        {"error": "You don't have the required permissions."},
        status=status.HTTP_403_FORBIDDEN,
    )


def allow_finance_access(view_func):
    """The requesting user must be a workspace admin or on the finance allowlist."""

    @wraps(view_func)
    def _wrapped_view(instance, request, *args, **kwargs):
        if has_finance_access(request.user, kwargs["slug"]):
            return view_func(instance, request, *args, **kwargs)
        return _forbidden()

    return _wrapped_view


def allow_collections_access(view_func):
    """The requesting user needs at least the collections (cobranza) role."""

    @wraps(view_func)
    def _wrapped_view(instance, request, *args, **kwargs):
        if has_collections_access(request.user, kwargs["slug"]):
            return view_func(instance, request, *args, **kwargs)
        return _forbidden()

    return _wrapped_view


def allow_finance_admin(view_func):
    """The requesting user must be a workspace admin (allowlist management)."""

    @wraps(view_func)
    def _wrapped_view(instance, request, *args, **kwargs):
        if is_workspace_admin(request.user, kwargs["slug"]):
            return view_func(instance, request, *args, **kwargs)
        return _forbidden()

    return _wrapped_view
