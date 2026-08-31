# Sintergica CE extension: assistant endpoints (session-authenticated app API).

from django.db.models import Count
from django.http import StreamingHttpResponse
from rest_framework import status
from rest_framework.response import Response

from plane.app.views.base import BaseAPIView
from django.utils import timezone

from plane.assistant.llm import (
    AssistantNotConfigured,
    get_config,
    month_token_usage,
    next_sequence,
    run_turn,
    sse,
    wrap_tool_result,
)
from plane.assistant.models import Action, Conversation, Message
from plane.assistant.permissions import (
    accessible_project_ids,
    allow_assistant,
    get_workspace,
    writable_project_ids,
)
from plane.assistant.registry import TOOL_SCHEMAS, WRITE_TOOLS, execute_action
from plane.assistant.serializers import (
    ConversationDetailSerializer,
    ConversationSerializer,
)
from plane.assistant.tools import ToolContext
# plane.finance no importa plane.assistant, así que no hay ciclo.
from plane.finance.permissions import finance_role

MAX_PROMPT_CHARS = 8000


def _build_context(request, slug):
    workspace = get_workspace(slug)
    return ToolContext(
        user=request.user,
        workspace=workspace,
        slug=slug,
        project_ids=accessible_project_ids(request.user, slug),
        finance_role=finance_role(request.user, slug),
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
                # Depende del usuario, no de la instancia: un invitado sin
                # proyectos escribibles no ve las herramientas de escritura.
                "can_write": bool(writable_project_ids(request.user, slug)),
                # El frontend lo usa para sugerir preguntas de finanzas sólo a
                # quien puede obtener respuesta.
                "finance_role": finance_role(request.user, slug),
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
        can_write = bool(writable_project_ids(request.user, slug))

        # Si quedaron acciones sin decidir de un turno anterior, sus tool_calls
        # están sin respuesta y el proveedor rechazaría la petición. Se dan por
        # no confirmadas: el usuario ha seguido escribiendo en vez de pulsar.
        _close_pending_actions(conversation, reason="El usuario continuó sin confirmarla.")

        # Generador ASÍNCRONO: uno síncrono NO se transmite. Django lo consume
        # con `await sync_to_async(list)(...)`, es decir lo materializa entero
        # antes de emitir el primer byte.
        async def stream():
            yield sse("start", {"conversation_id": str(conversation.id)})
            try:
                async for frame in run_turn(conversation, ctx, config, can_write=can_write):
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


def _close_pending_actions(conversation, reason, decided=None, decided_result=None, decided_status=None):
    """Responde a TODOS los tool_calls de escritura que sigan sin respuesta.

    Es lo que mantiene el transcript válido: un turno del asistente con
    tool_calls y sin su mensaje `tool` correspondiente hace que el proveedor
    rechace la siguiente petición. `decided` es la acción que la persona sí
    resolvió; sus hermanas del mismo turno se marcan como no confirmadas.
    """
    pending = list(Action.objects.filter(conversation=conversation, status="pending"))
    if not pending:
        return
    for action in pending:
        if decided is not None and action.id == decided.id:
            payload = decided_result or {}
            # El estado lo decide quien llama, no la forma del resultado: un
            # rechazo tampoco trae "error" y se marcaba como ejecutado.
            status_value = decided_status or ("failed" if payload.get("error") else "executed")
        else:
            payload = {"cancelada": reason}
            status_value = "rejected"
        Message.objects.create(
            conversation=conversation,
            role="tool",
            content=wrap_tool_result(action.tool_name, payload),
            tool_call_id=action.tool_call_id,
            tool_name=action.tool_name,
            sequence=next_sequence(conversation),
        )
        action.status = status_value
        action.result = payload
        action.executed_at = timezone.now()
        action.save(update_fields=["status", "result", "executed_at", "updated_at"])


class AssistantActionEndpoint(BaseAPIView):
    """Confirma o descarta una acción propuesta y reanuda el turno.

    Nada del asistente escribe en el workspace sin pasar por aquí con
    decision="confirm": es el único sitio que llama a execute_action.
    """

    use_read_replica = False

    @allow_assistant
    def post(self, request, slug, pk):
        action = (
            Action.objects.filter(
                pk=pk, conversation__workspace__slug=slug, conversation__owner=request.user
            )
            .select_related("conversation")
            .first()
        )
        if not action:
            return Response({"error": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        if action.status != "pending":
            return Response(
                {"error": f"Esa acción ya está en estado '{action.status}'."},
                status=status.HTTP_409_CONFLICT,
            )

        decision = request.data.get("decision")
        if decision not in ("confirm", "reject"):
            return Response(
                {"error": "decision debe ser 'confirm' o 'reject'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        conversation = action.conversation
        config = get_config()
        if not config["enabled"] or not config["configured"]:
            return Response(
                {"error": "El asistente no está configurado."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        ctx = _build_context(request, slug)
        can_write = bool(writable_project_ids(request.user, slug))

        if decision == "confirm":
            if action.tool_name not in WRITE_TOOLS:
                return Response(
                    {"error": "Esa acción no es una herramienta de escritura."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            # execute_action revalida permisos y existencia: entre la propuesta
            # y el clic pueden haber cambiado.
            result = execute_action(action.tool_name, ctx, action.arguments)
        else:
            result = {"cancelada": "El usuario rechazó la acción."}

        _close_pending_actions(
            conversation,
            reason="El usuario confirmó otra acción de la misma propuesta.",
            decided=action,
            decided_result=result,
            decided_status=(
                "rejected"
                if decision == "reject"
                else ("failed" if result.get("error") else "executed")
            ),
        )

        async def stream():
            yield sse(
                "action_result",
                {"id": str(action.id), "decision": decision, "result": result},
            )
            try:
                async for frame in run_turn(conversation, ctx, config, can_write=can_write):
                    yield frame
            except Exception as exc:  # noqa: BLE001
                yield sse("error", {"code": exc.__class__.__name__, "message": str(exc)[:500]})

        response = StreamingHttpResponse(stream(), content_type="text/event-stream")
        response["Cache-Control"] = "no-cache, no-transform"
        response["X-Accel-Buffering"] = "no"
        response["Content-Encoding"] = "identity"
        return response
