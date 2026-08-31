# Sintergica CE extension: chat message attachments.
#
# Same presigned-upload flow as the drive (FileAsset with a free-text
# entity_type, no migration): POST creates the row + presigned S3 POST, PATCH
# marks it uploaded after the browser pushes to storage, GET redirects to a
# signed download URL. Authorization is the channel's visibility — the asset
# remembers its channel in attributes.channel_id and the editor embeds the
# asset id inside message_html (image-component), so no message FK is needed.

import uuid

from django.conf import settings
from django.http import HttpResponseRedirect
from rest_framework import status
from rest_framework.response import Response

from plane.app.views.base import BaseAPIView
from plane.chat.permissions import allow_chat, channel_queryset
from plane.db.models import FileAsset, Workspace
from plane.settings.storage import S3Storage
from plane.utils.path_validator import sanitize_filename

CHAT_ENTITY_TYPE = "CHAT"
CHAT_FILE_SIZE_LIMIT = 25 * 1024 * 1024  # 25MB per message attachment


def _bad_request(detail):
    return Response({"error": detail}, status=status.HTTP_400_BAD_REQUEST)


def _get_channel(request, slug, channel_id):
    return channel_queryset(request.user, slug).filter(pk=channel_id).first()


class ChatAssetsEndpoint(BaseAPIView):
    use_read_replica = False

    @allow_chat
    def post(self, request, slug, channel_id):
        channel = _get_channel(request, slug, channel_id)
        if channel is None:
            return Response({"error": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        name = request.data.get("name")
        if not name or not str(name).strip():
            return _bad_request("Name is required.")
        name = sanitize_filename(name)
        file_type = request.data.get("type") or "application/octet-stream"
        try:
            size = int(request.data.get("size", 0))
        except (TypeError, ValueError):
            return _bad_request("Invalid size.")
        if size <= 0:
            return _bad_request("Size is required.")
        if size > CHAT_FILE_SIZE_LIMIT:
            return Response(
                {"error": "File size exceeds the chat limit.", "limit": CHAT_FILE_SIZE_LIMIT},
                status=status.HTTP_400_BAD_REQUEST,
            )

        workspace = Workspace.objects.get(slug=slug)

        # Opportunistic cleanup: this user's CHAT uploads that never finished
        # (browser closed mid-upload) are dead weight — sweep the >24h ones
        # while we are here, instead of configuring a beat schedule.
        from datetime import timedelta

        from django.utils import timezone

        FileAsset.objects.filter(
            entity_type=CHAT_ENTITY_TYPE,
            created_by=request.user,
            is_uploaded=False,
            created_at__lt=timezone.now() - timedelta(hours=24),
        ).delete()

        asset_key = f"{workspace.id}/{uuid.uuid4().hex}-{name}"
        asset = FileAsset.objects.create(
            attributes={
                "name": name,
                "type": file_type,
                "size": size,
                "channel_id": str(channel.id),
            },
            asset=asset_key,
            size=size,
            workspace=workspace,
            project_id=channel.project_id,
            created_by=request.user,
            entity_type=CHAT_ENTITY_TYPE,
        )
        storage = S3Storage(request=request)
        presigned_url = storage.generate_presigned_post(
            object_name=asset_key, file_type=file_type, file_size=size
        )
        if presigned_url is None:
            return Response(
                {"error": "Could not generate the upload URL."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        return Response(
            {"upload_data": presigned_url, "asset_id": str(asset.id)},
            status=status.HTTP_200_OK,
        )


class ChatAssetDetailEndpoint(BaseAPIView):
    use_read_replica = False

    def _get_asset(self, request, slug, channel_id, asset_id):
        channel = _get_channel(request, slug, channel_id)
        if channel is None:
            return None
        return FileAsset.objects.filter(
            pk=asset_id,
            workspace__slug=slug,
            entity_type=CHAT_ENTITY_TYPE,
            attributes__channel_id=str(channel.id),
        ).first()

    @allow_chat
    def patch(self, request, slug, channel_id, asset_id):
        """The browser confirms the S3 upload landed."""
        asset = self._get_asset(request, slug, channel_id, asset_id)
        if asset is None:
            return Response({"error": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        if asset.created_by_id != request.user.id:
            return Response(
                {"error": "Only the uploader can confirm an asset."},
                status=status.HTTP_403_FORBIDDEN,
            )
        asset.is_uploaded = True
        asset.save()
        return Response({"id": str(asset.id)}, status=status.HTTP_200_OK)

    @allow_chat
    def get(self, request, slug, channel_id, asset_id):
        asset = self._get_asset(request, slug, channel_id, asset_id)
        if asset is None or not asset.is_uploaded:
            return Response({"error": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        attributes = asset.attributes or {}
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
