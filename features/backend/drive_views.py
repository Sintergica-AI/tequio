# Sintergica CE extension: file manager ("Drive") endpoints, workspace and
# project scoped. Files live in MinIO/S3 through the existing FileAsset model
# (entity_type "DRIVE" — free-text column, so no DB migration is needed).
# Uploads go straight to object storage via presigned POST, downloads via
# presigned GET redirects — the Django server never proxies file bytes.
#
# An entry is either an uploaded file (kind="file") or an external link
# (kind="link", e.g. a Google Drive URL). Both carry free-text tags and an
# optional module relation; all of it rides in FileAsset.attributes, so there
# is still no migration.
# Derived from plane/app/views/asset/v2.py (AGPL-3.0-only).

# Python imports
import os
import uuid

# Django imports
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.http import HttpResponseRedirect
from django.utils import timezone

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.app.permissions import ROLE, allow_permission
from plane.app.views.base import BaseAPIView
from plane.bgtasks.storage_metadata_task import get_asset_object_metadata
from plane.db.models import FileAsset, Module, ProjectMember, Workspace, WorkspaceMember
from plane.settings.storage import S3Storage
from plane.utils.path_validator import sanitize_filename

DRIVE_ENTITY_TYPE = "DRIVE"

KIND_FILE = "file"
KIND_LINK = "link"

# Dedicated size limit for the drive (defaults to 100 MB). The global
# FILE_SIZE_LIMIT (5 MB by default) is meant for covers/avatars and is far too
# small for a file manager. Uploads never pass through Django, so this does not
# interact with DATA_UPLOAD_MAX_MEMORY_SIZE.
DRIVE_FILE_SIZE_LIMIT = int(os.environ.get("DRIVE_FILE_SIZE_LIMIT", 104857600))

MAX_TAGS = 20
MAX_TAG_LENGTH = 50
MAX_URL_LENGTH = 2000

# Only ever accept web URLs. Without this an attacker-supplied "javascript:..."
# or "data:..." value would be handed straight to an anchor/iframe in the UI.
_url_validator = URLValidator(schemes=["http", "https"])


def _clean_url(raw):
    """Return a validated http(s) URL or raise ValueError."""
    if not raw or not isinstance(raw, str):
        raise ValueError("A URL is required.")
    url = raw.strip()
    if len(url) > MAX_URL_LENGTH:
        raise ValueError("The URL is too long.")
    try:
        _url_validator(url)
    except ValidationError:
        raise ValueError("Enter a valid http(s) URL.")
    return url


def _clean_tags(raw):
    """Normalize a list of free-text tags: trim, drop empties, dedupe, cap."""
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise ValueError("Tags must be a list.")
    tags = []
    for item in raw:
        if not isinstance(item, str):
            continue
        tag = " ".join(item.split())[:MAX_TAG_LENGTH].strip()
        if tag and tag.lower() not in [t.lower() for t in tags]:
            tags.append(tag)
    return tags[:MAX_TAGS]


def _clean_module_id(raw, project_id):
    """Validate that the module exists inside this project. Returns str or None."""
    if raw in (None, ""):
        return None
    if not project_id:
        raise ValueError("Files can only be linked to a module inside a project.")
    try:
        module_uuid = uuid.UUID(str(raw))
    except (ValueError, AttributeError, TypeError):
        raise ValueError("Invalid module.")
    if not Module.objects.filter(pk=module_uuid, project_id=project_id).exists():
        raise ValueError("The module does not belong to this project.")
    return str(module_uuid)


def _serialize_asset(asset):
    attributes = asset.attributes or {}
    return {
        "id": str(asset.id),
        "name": attributes.get("name", ""),
        "type": attributes.get("type", ""),
        "folder": attributes.get("folder", ""),
        "kind": attributes.get("kind", KIND_FILE),
        "url": attributes.get("url", ""),
        "tags": attributes.get("tags", []),
        "module_id": attributes.get("module_id"),
        "size": asset.size,
        "project_id": str(asset.project_id) if asset.project_id else None,
        "created_at": asset.created_at,
        "updated_at": asset.updated_at,
        "created_by": str(asset.created_by_id) if asset.created_by_id else None,
        "created_by_display_name": (asset.created_by.display_name if asset.created_by_id else None),
        "is_uploaded": asset.is_uploaded,
    }


class DriveBaseMixin:
    def _queryset(self, slug, project_id=None):
        qs = FileAsset.objects.filter(
            workspace__slug=slug,
            entity_type=DRIVE_ENTITY_TYPE,
            is_deleted=False,
        ).select_related("created_by")
        if project_id is None:
            qs = qs.filter(project__isnull=True)
        else:
            qs = qs.filter(project_id=project_id)
        return qs

    def _list(self, request, slug, project_id=None):
        qs = self._queryset(slug, project_id).filter(is_uploaded=True)
        search = request.query_params.get("search")
        if search:
            qs = qs.filter(attributes__name__icontains=search)
        order_by = request.query_params.get("order_by", "-created_at")
        if order_by.lstrip("-") not in ["created_at", "updated_at", "size"]:
            order_by = "-created_at"
        qs = qs.order_by(order_by)
        return Response([_serialize_asset(a) for a in qs], status=status.HTTP_200_OK)

    def _create(self, request, slug, project_id=None):
        name = request.data.get("name")
        if not name or not str(name).strip():
            return Response({"error": "Name is required."}, status=status.HTTP_400_BAD_REQUEST)
        kind = request.data.get("kind", KIND_FILE)
        if kind not in (KIND_FILE, KIND_LINK):
            return Response({"error": "Invalid kind."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            tags = _clean_tags(request.data.get("tags")) or []
            module_id = _clean_module_id(request.data.get("module_id"), project_id)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        workspace = Workspace.objects.get(slug=slug)
        folder = request.data.get("folder", "") or ""

        # ---------------------------------------------------------------- link
        if kind == KIND_LINK:
            try:
                url = _clean_url(request.data.get("url"))
            except ValueError as e:
                return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
            link_name = " ".join(str(name).split())[:255]
            asset = FileAsset.objects.create(
                attributes={
                    "name": link_name,
                    "type": "link",
                    "size": 0,
                    "folder": folder,
                    "kind": KIND_LINK,
                    "url": url,
                    "tags": tags,
                    "module_id": module_id,
                },
                asset="",
                size=0,
                workspace=workspace,
                project_id=project_id,
                created_by=request.user,
                entity_type=DRIVE_ENTITY_TYPE,
                # nothing to upload — the entry is complete on creation
                is_uploaded=True,
            )
            return Response(_serialize_asset(asset), status=status.HTTP_201_CREATED)

        # ---------------------------------------------------------------- file
        name = sanitize_filename(name)
        type = request.data.get("type") or "application/octet-stream"
        try:
            size = int(request.data.get("size", 0))
        except (TypeError, ValueError):
            return Response({"error": "Invalid size."}, status=status.HTTP_400_BAD_REQUEST)
        if size <= 0:
            return Response({"error": "Size is required."}, status=status.HTTP_400_BAD_REQUEST)
        if size > DRIVE_FILE_SIZE_LIMIT:
            return Response(
                {"error": "File size exceeds the drive limit.", "limit": DRIVE_FILE_SIZE_LIMIT},
                status=status.HTTP_400_BAD_REQUEST,
            )

        asset_key = f"{workspace.id}/{uuid.uuid4().hex}-{name}"
        asset = FileAsset.objects.create(
            attributes={
                "name": name,
                "type": type,
                "size": size,
                "folder": folder,
                "kind": KIND_FILE,
                "tags": tags,
                "module_id": module_id,
            },
            asset=asset_key,
            size=size,
            workspace=workspace,
            project_id=project_id,
            created_by=request.user,
            entity_type=DRIVE_ENTITY_TYPE,
        )

        storage = S3Storage(request=request)
        presigned_url = storage.generate_presigned_post(object_name=asset_key, file_type=type, file_size=size)
        if presigned_url is None:
            return Response(
                {"error": "Could not generate the upload URL."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        return Response(
            {"upload_data": presigned_url, "asset_id": str(asset.id)},
            status=status.HTTP_200_OK,
        )

    def _patch(self, request, slug, asset_id, project_id=None):
        asset = self._queryset(slug, project_id).get(id=asset_id)
        attributes = dict(asset.attributes or {})
        is_link = attributes.get("kind") == KIND_LINK

        update_fields = ["attributes"]
        # confirming an upload — links are already complete on creation
        if not asset.is_uploaded and not is_link:
            asset.is_uploaded = True
            update_fields.append("is_uploaded")
            if not asset.storage_metadata:
                get_asset_object_metadata.delay(asset_id=str(asset_id))

        new_name = request.data.get("name")
        if new_name and str(new_name).strip():
            attributes["name"] = (
                " ".join(str(new_name).split())[:255] if is_link else sanitize_filename(new_name)
            )
        if "folder" in request.data:
            attributes["folder"] = request.data.get("folder") or ""
        try:
            if "tags" in request.data:
                attributes["tags"] = _clean_tags(request.data.get("tags")) or []
            if "module_id" in request.data:
                attributes["module_id"] = _clean_module_id(request.data.get("module_id"), project_id)
            if "url" in request.data and is_link:
                attributes["url"] = _clean_url(request.data.get("url"))
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        asset.attributes = attributes
        asset.save(update_fields=update_fields)
        return Response(_serialize_asset(asset), status=status.HTTP_200_OK)

    def _delete(self, request, slug, asset_id, project_id=None, is_admin=False):
        asset = self._queryset(slug, project_id).get(id=asset_id)
        if asset.created_by_id != request.user.id and not is_admin:
            return Response(
                {"error": "Only the uploader or an admin can delete this file."},
                status=status.HTTP_403_FORBIDDEN,
            )
        asset.is_deleted = True
        asset.deleted_at = timezone.now()
        asset.save(update_fields=["is_deleted", "deleted_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _download(self, request, slug, asset_id, project_id=None):
        asset = self._queryset(slug, project_id).get(id=asset_id)
        attributes = asset.attributes or {}
        # External links have no object in storage. Return the URL instead of
        # redirecting, so this endpoint can never be used as an open redirect.
        if attributes.get("kind") == KIND_LINK:
            return Response(
                {"kind": KIND_LINK, "url": attributes.get("url", "")},
                status=status.HTTP_200_OK,
            )
        if not asset.is_uploaded:
            return Response(
                {"error": "The requested asset could not be found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        content_type = attributes.get("type", "application/octet-stream")
        disposition = "inline" if request.query_params.get("disposition") == "inline" else "attachment"
        # never serve script-capable content inline
        if content_type in settings.SCRIPT_CAPABLE_MIME_TYPES:
            disposition = "attachment"
        storage = S3Storage(request=request)
        signed_url = storage.generate_presigned_url(
            object_name=asset.asset.name,
            disposition=disposition,
            filename=attributes.get("name"),
        )
        return HttpResponseRedirect(signed_url)


class WorkspaceDriveEndpoint(DriveBaseMixin, BaseAPIView):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], level="WORKSPACE")
    def get(self, request, slug):
        return self._list(request, slug)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER], level="WORKSPACE")
    def post(self, request, slug):
        return self._create(request, slug)


class WorkspaceDriveAssetEndpoint(DriveBaseMixin, BaseAPIView):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], level="WORKSPACE")
    def get(self, request, slug, asset_id):
        return self._download(request, slug, asset_id)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER], level="WORKSPACE")
    def patch(self, request, slug, asset_id):
        return self._patch(request, slug, asset_id)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER], level="WORKSPACE")
    def delete(self, request, slug, asset_id):
        is_admin = WorkspaceMember.objects.filter(
            workspace__slug=slug,
            member=request.user,
            role=ROLE.ADMIN.value,
            is_active=True,
        ).exists()
        return self._delete(request, slug, asset_id, is_admin=is_admin)


class ProjectDriveEndpoint(DriveBaseMixin, BaseAPIView):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id):
        return self._list(request, slug, project_id)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def post(self, request, slug, project_id):
        return self._create(request, slug, project_id)


class ProjectDriveAssetEndpoint(DriveBaseMixin, BaseAPIView):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id, asset_id):
        return self._download(request, slug, asset_id, project_id)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def patch(self, request, slug, project_id, asset_id):
        return self._patch(request, slug, asset_id, project_id)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def delete(self, request, slug, project_id, asset_id):
        is_admin = ProjectMember.objects.filter(
            workspace__slug=slug,
            project_id=project_id,
            member=request.user,
            role=ROLE.ADMIN.value,
            is_active=True,
        ).exists()
        return self._delete(request, slug, asset_id, project_id, is_admin=is_admin)
