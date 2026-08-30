# Sintergica CE extension: assistant endpoints (session-authenticated app API).

from django.db.models import Count
from django.http import StreamingHttpResponse
from rest_framework import status
from rest_framework.response import Response

from plane.app.views.base import BaseAPIView
from plane.assistant.llm import (
    AssistantNotConfigured,
    get_config,
    month_token_usage,
    next_sequence,
    run_turn,
    sse,
)
from plane.assistant.models import Conversation, Message
from plane.assistant.permissions import (
    accessible_project_ids,
    allow_assistant,
    get_workspace,
)
from plane.assistant.registry import TOOL_SCHEMAS
from plane.assistant.serializers import (
    ConversationDetailSerializer,
    ConversationSerializer,
)
from plane.assistant.tools import ToolContext

MAX_PROMPT_CHARS = 8000


def _build_context(request, slug):
    workspace = get_workspace(slug)
    return ToolContext(
        user=request.user,
        workspace=workspace,
        slug=slug,
        project_ids=accessible_project_ids(request.user, slug),
    )


class AssistantConfigEndpoint(BaseAPIView):
    """What the panel needs to know before rendering anything."""

    @allow_assistant
    def get(self, request, slug):
        config = get_config()
        workspace = get_workspace(slug)
        used = month_token_usage(workspace)
        return Response(
            {
                "enabled": config["enabled"] and config["configured"],
                "configured": config["configured"],
                "provider": config["provider"],
                "model": config["model"],
                "models": config["models"],
                "tools": [t["function"]["name"] for t in TOOL_SCHEMAS],
                "can_write": False,  # phase 1 is read-only
                "usage": {
                    "tokens_this_month": used,
                    "monthly_token_cap": config["monthly_token_cap"],
                    "exhausted": used >= config["monthly_token_cap"],
                },
            },
            status=status.HTTP_200_OK,
        )


class ConversationsEndpoint(BaseAPIView):
    @allow_assistant
    def get(self, request, slug):
        rows = (
            Conversation.objects.filter(
                workspace__slug=slug, owner=request.user, archived_at__isnull=True
            )
            .annotate(message_count=Count("messages"))
            .order_by("-updated_at")[:100]
        )
        return Response(ConversationSerializer(rows, many=True).data, status=status.HTTP_200_OK)

    @allow_assistant
    def post(self, request, slug):
        config = get_config()
        workspace = get_workspace(slug)
        requested_model = request.data.get("model")
        if requested_model and requested_model not in config["models"]:
            return Response(
                {
                    "error": "Modelo no permitido en esta instancia.",
                    "allowed": config["models"],
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        conversation = Conversation.objects.create(
            workspace=workspace,
            owner=request.user,
            title=request.data.get("title", "") or "",
            provider=config["provider"] or "",
            model=requested_model or config["model"] or "",
            context=request.data.get("context") or {},
        )
        return Response(
            ConversationDetailSerializer(conversation).data, status=status.HTTP_201_CREATED
        )


class ConversationDetailEndpoint(BaseAPIView):
    def _get(self, request, slug, pk):
        # Conversations are private to their owner — no admin override, on
        # purpose: people paste half-formed thoughts into a chat box.
        return Conversation.objects.filter(
            pk=pk, workspace__slug=slug, owner=request.user
        ).first()

    @allow_assistant
    def get(self, request, slug, pk):
        conversation = self._get(request, slug, pk)
        if not conversation:
            return Response({"error": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(
            ConversationDetailSerializer(conversation).data, status=status.HTTP_200_OK
        )

    @allow_assistant
    def patch(self, request, slug, pk):
        conversation = self._get(request, slug, pk)
        if not conversation:
            return Response({"error": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = ConversationSerializer(conversation, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)

    @allow_assistant
    def delete(self, request, slug, pk):
        conversation = self._get(request, slug, pk)
        if not conversation:
            return Response({"error": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        conversation.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ConversationMessagesEndpoint(BaseAPIView):
    """POST a user message, get the assistant's turn back as an SSE stream."""

    use_read_replica = False

    @allow_assistant
    def post(self, request, slug, pk):
        conversation = Conversation.objects.filter(
            pk=pk, workspace__slug=slug, owner=request.user
        ).first()
        if not conversation:
            return Response({"error": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        prompt = (request.data.get("content") or "").strip()
        if not prompt:
            return Response({"error": "Falta 'content'."}, status=status.HTTP_400_BAD_REQUEST)
        if len(prompt) > MAX_PROMPT_CHARS:
            return Response(
                {"error": f"El mensaje excede {MAX_PROMPT_CHARS} caracteres."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        config = get_config()
        if not config["enabled"] or not config["configured"]:
            return Response(
                {
                    "error": "El asistente no está configurado. Define proveedor, "
                    "clave y modelo en /god-mode/ai/."
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        # Quota is checked before the stream opens so the client sees a real
        # status code instead of an error event inside a 200.
        used = month_token_usage(conversation.workspace)
        if used >= config["monthly_token_cap"]:
            return Response(
                {
                    "error": "Se alcanzó el tope de tokens del mes para este workspace.",
                    "tokens_this_month": used,
                    "monthly_token_cap": config["monthly_token_cap"],
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        # El modelo viaja con el mensaje a propósito. Cambiarlo con un PATCH
        # aparte y enviar acto seguido era una carrera: el POST podía llegar
        # antes que el PATCH y la respuesta salía con el modelo anterior.
        requested_model = request.data.get("model")
        if requested_model:
            if requested_model not in config["models"]:
                return Response(
                    {"error": "Modelo no permitido en esta instancia.", "allowed": config["models"]},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if conversation.model != requested_model:
                conversation.model = requested_model
                conversation.save(update_fields=["model"])

        if request.data.get("context"):
            conversation.context = request.data["context"]
            conversation.save(update_fields=["context"])

        Message.objects.create(
            conversation=conversation,
            role="user",
            content=prompt,
            sequence=next_sequence(conversation),
        )
        if not conversation.title:
            conversation.title = prompt[:80]
            conversation.save(update_fields=["title"])

        ctx = _build_context(request, slug)

        # Generador ASÍNCRONO: uno síncrono NO se transmite. Django lo consume
        # con `await sync_to_async(list)(...)`, es decir lo materializa entero
        # antes de emitir el primer byte.
        async def stream():
            yield sse("start", {"conversation_id": str(conversation.id)})
            try:
                async for frame in run_turn(conversation, ctx, config):
                    yield frame
            except AssistantNotConfigured as exc:
                yield sse("error", {"code": "NotConfigured", "message": str(exc)})
            except Exception as exc:  # noqa: BLE001
                yield sse("error", {"code": exc.__class__.__name__, "message": str(exc)[:500]})

        response = StreamingHttpResponse(stream(), content_type="text/event-stream")
        response["Cache-Control"] = "no-cache, no-transform"
        # Caddy does not buffer by default, but say so explicitly in case another
        # proxy ever sits in front: buffering turns the stream into one blob.
        response["X-Accel-Buffering"] = "no"
        # Plane runs django.middleware.gzip.GZipMiddleware, which compresses
        # streaming responses too: zlib holds the small SSE frames until its
        # buffer fills, so the browser saw nothing until the turn had finished.
        # Declaring the encoding is the middleware's own opt-out (it returns
        # early when Content-Encoding is already set) and it is accurate —
        # "identity" means no transformation was applied.
        response["Content-Encoding"] = "identity"
        return response
