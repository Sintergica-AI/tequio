"""Prueba funcional del chat (fase 1: backend REST): canales, #general,
mensajes con cursor y catch-up, hilos, reacciones, leídos, vínculos de work
items, menciones→Notification y permisos. Corre dentro del contenedor api.
No deja datos."""

import json
import os
from urllib.parse import quote

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "plane.settings.production")
django.setup()

from django.test import Client  # noqa: E402
from plane.chat.models import Channel, ChannelMember, ChatMessage  # noqa: E402
from plane.chat.tasks import chat_message_notify_task  # noqa: E402
from plane.db.models import (  # noqa: E402
    Issue,
    Notification,
    ProjectMember,
    User,
    Workspace,
    WorkspaceMember,
)

OK, FAIL = "\033[92mOK\033[0m", "\033[91mFALLO\033[0m"
results = []
J = "application/json"
MARK = "verify10-tmp"


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(f"  {OK if cond else FAIL}  {name}" + (f" — {detail}" if detail else ""))


ws = Workspace.objects.first()
slug = ws.slug
admin = WorkspaceMember.objects.filter(workspace=ws, role=20, is_active=True).first().member
pm = (
    ProjectMember.objects.filter(member=admin, is_active=True, role=20, workspace=ws)
    .select_related("project")
    .first()
)
project = pm.project
c = Client()
c.force_login(admin)
base = f"/api/workspaces/{slug}/chat"

# Otro miembro del workspace, para menciones y no-leídos.
other = (
    WorkspaceMember.objects.filter(workspace=ws, is_active=True)
    .exclude(member=admin)
    .select_related("member")
    .first()
)
other_user = other.member if other else None

general_existed = Channel.objects.filter(project=project, is_general=True).exists()
created_channels = []

try:
    print("CANALES")
    r = c.get(f"{base}/channels/?project_id={project.id}")
    check("listar canales de proyecto", r.status_code == 200, f"HTTP {r.status_code}")
    rows = r.json() if r.status_code == 200 else []
    check("#general se materializa solo", any(row["is_general"] for row in rows))

    r = c.post(
        f"{base}/channels/",
        data=json.dumps({"name": f"#{MARK}-ws", "description": "temporal"}),
        content_type=J,
    )
    check("crear canal de workspace (y se le cae el #)", r.status_code == 201 and r.json()["name"] == f"{MARK}-ws")
    ws_channel = r.json()
    created_channels.append(ws_channel["id"])

    r = c.post(
        f"{base}/channels/",
        data=json.dumps({"name": f"{MARK.upper()}-WS"}),
        content_type=J,
    )
    check("duplicado (case-insensitive) → 400", r.status_code == 400, f"HTTP {r.status_code}")

    r = c.post(
        f"{base}/channels/",
        data=json.dumps({"name": f"{MARK}-proj", "project_id": str(project.id)}),
        content_type=J,
    )
    check("crear canal de proyecto", r.status_code == 201)
    proj_channel = r.json()
    created_channels.append(proj_channel["id"])
    ch = proj_channel["id"]

    general_id = next((row["id"] for row in rows if row["is_general"]), None)
    r = c.patch(
        f"{base}/channels/{general_id}/",
        data=json.dumps({"name": "otro"}),
        content_type=J,
    )
    check("#general no se renombra", r.status_code == 400, f"HTTP {r.status_code}")
    r = c.delete(f"{base}/channels/{general_id}/")
    check("#general no se borra", r.status_code == 400, f"HTTP {r.status_code}")

    print("\nMENSAJES")
    msg_ids = []
    for i in range(3):
        r = c.post(
            f"{base}/channels/{ch}/messages/",
            data=json.dumps({"message_html": f"<p>mensaje {i}</p>"}),
            content_type=J,
        )
        assert r.status_code == 201, r.content
        msg_ids.append(r.json()["id"])
    check("crear mensajes", len(msg_ids) == 3)
    check("stripped calculado", r.json()["message_stripped"] == "mensaje 2")

    r = c.post(
        f"{base}/channels/{ch}/messages/",
        data=json.dumps({"message_html": "<p>   </p>"}),
        content_type=J,
    )
    check("mensaje vacío → 400", r.status_code == 400, f"HTTP {r.status_code}")

    r = c.get(f"{base}/channels/{ch}/messages/?limit=2")
    page = r.json()
    check(
        "página inicial (los 2 más nuevos, asc)",
        r.status_code == 200
        and [m["id"] for m in page["results"]] == msg_ids[1:]
        and page["has_more"] is True,
    )
    r = c.get(f"{base}/channels/{ch}/messages/?limit=2&cursor={quote(page['next_cursor'])}")
    older = r.json()
    check(
        "cursor hacia atrás",
        r.status_code == 200
        and [m["id"] for m in older["results"]] == msg_ids[:1]
        and older["has_more"] is False,
    )

    first_created = ChatMessage.objects.get(pk=msg_ids[0]).created_at
    r = c.get(
        f"{base}/channels/{ch}/messages/?created_at__gt={quote(first_created.isoformat())}"
    )
    check(
        "catch-up created_at__gt",
        r.status_code == 200 and [m["id"] for m in r.json()["results"]] == msg_ids[1:],
    )

    print("\nHILOS")
    root = msg_ids[0]
    r = c.post(
        f"{base}/channels/{ch}/messages/",
        data=json.dumps({"message_html": "<p>respuesta 1</p>", "parent_id": root}),
        content_type=J,
    )
    check("responder en hilo", r.status_code == 201 and r.json()["parent"] == root)
    reply1 = r.json()["id"]
    r = c.post(
        f"{base}/channels/{ch}/messages/",
        data=json.dumps({"message_html": "<p>respuesta a respuesta</p>", "parent_id": reply1}),
        content_type=J,
    )
    check("reply-a-reply cuelga de la raíz", r.status_code == 201 and r.json()["parent"] == root)
    r = c.get(f"{base}/channels/{ch}/messages/{root}/thread/")
    thread = r.json()
    check(
        "GET thread (raíz + 2 respuestas, reply_count anotado)",
        r.status_code == 200
        and len(thread["replies"]) == 2
        and thread["root"]["reply_count"] == 2,
    )
    r = c.get(f"{base}/channels/{ch}/messages/?limit=10")
    check(
        "las respuestas no salen en la lista raíz",
        all(m["parent"] is None for m in r.json()["results"]),
    )

    print("\nEDICIÓN Y BORRADO")
    r = c.patch(
        f"{base}/channels/{ch}/messages/{msg_ids[1]}/",
        data=json.dumps({"message_html": "<p>editado</p>"}),
        content_type=J,
    )
    check("editar propio → edited_at", r.status_code == 200 and r.json()["edited_at"])
    r = c.delete(f"{base}/channels/{ch}/messages/{root}/")
    check("borrar raíz con respuestas → 204", r.status_code == 204, f"HTTP {r.status_code}")
    r = c.get(f"{base}/channels/{ch}/messages/{root}/thread/")
    check(
        "tombstone: hilo sigue, contenido fuera",
        r.status_code == 200
        and r.json()["root"]["is_removed"] is True
        and r.json()["root"]["message_html"] == "",
    )
    r = c.delete(f"{base}/channels/{ch}/messages/{msg_ids[2]}/")
    ok_del = r.status_code == 204
    r = c.get(f"{base}/channels/{ch}/messages/?limit=10")
    check(
        "borrar sin respuestas desaparece",
        ok_del and msg_ids[2] not in [m["id"] for m in r.json()["results"]],
    )

    print("\nREACCIONES")
    r = c.post(
        f"{base}/channels/{ch}/messages/{msg_ids[1]}/reactions/",
        data=json.dumps({"reaction": "128077"}),
        content_type=J,
    )
    check("reaccionar", r.status_code == 200, f"HTTP {r.status_code}")
    r = c.post(
        f"{base}/channels/{ch}/messages/{msg_ids[1]}/reactions/",
        data=json.dumps({"reaction": "128077"}),
        content_type=J,
    )
    check("reacción duplicada idempotente", r.status_code == 200)
    r = c.get(f"{base}/channels/{ch}/messages/?limit=10")
    row = next(m for m in r.json()["results"] if m["id"] == msg_ids[1])
    check("una sola reacción serializada", len(row["reactions"]) == 1)
    r = c.delete(f"{base}/channels/{ch}/messages/{msg_ids[1]}/reactions/128077/")
    check("quitar reacción", r.status_code == 204, f"HTTP {r.status_code}")

    print("\nLEÍDOS")
    if other_user and ProjectMember.objects.filter(project=project, member=other_user, is_active=True).exists():
        c2 = Client()
        c2.force_login(other_user)
        r = c2.get(f"{base}/unreads/")
        mine = next((x for x in r.json() if x["channel_id"] == ch), None)
        check("otro usuario ve no-leídos", mine is not None and mine["unread_count"] > 0)
        r = c2.post(f"{base}/channels/{ch}/read/", data=json.dumps({}), content_type=J)
        check("marcar leído", r.status_code == 200 and r.json()["last_read_at"])
        r = c2.get(f"{base}/unreads/")
        mine = next((x for x in r.json() if x["channel_id"] == ch), None)
        check("no-leídos vuelve a 0", mine is not None and mine["unread_count"] == 0)
    else:
        print("  (sin segundo usuario con acceso al proyecto — saltado)")

    print("\nWORK ITEMS")
    issue = Issue.objects.filter(project=project).first()
    if issue:
        r = c.post(
            f"{base}/channels/{ch}/messages/{msg_ids[1]}/work-items/",
            data=json.dumps({"issue_id": str(issue.id)}),
            content_type=J,
        )
        links = r.json().get("work_item_links", []) if r.status_code == 200 else []
        check(
            "vincular work item (chip expandido)",
            r.status_code == 200
            and any(l["issue_id"] == str(issue.id) and l["sequence_id"] for l in links),
        )
        r = c.delete(
            f"{base}/channels/{ch}/messages/{msg_ids[1]}/work-items/{issue.id}/"
        )
        check("desvincular", r.status_code == 204, f"HTTP {r.status_code}")
    else:
        print("  (proyecto sin issues — saltado)")
    r = c.post(
        f"{base}/channels/{ch}/messages/{msg_ids[1]}/work-items/",
        data=json.dumps({"issue_id": "00000000-0000-0000-0000-000000000000"}),
        content_type=J,
    )
    check("issue inexistente → 404", r.status_code == 404, f"HTTP {r.status_code}")

    print("\nMENCIONES")
    if other_user:
        html = (
            f'<p>hola <mention-component entity_name="user_mention" '
            f'entity_identifier="{other_user.id}"></mention-component></p>'
        )
        r = c.post(
            f"{base}/channels/{ch}/messages/",
            data=json.dumps({"message_html": html}),
            content_type=J,
        )
        mid = r.json()["id"]
        # Directo, sin worker: lo que valida es la lógica, no celery.
        chat_message_notify_task(mid, None)
        notif = Notification.objects.filter(
            entity_name="chat_message", entity_identifier=mid, receiver=other_user
        ).first()
        expected = other_user and ProjectMember.objects.filter(
            project=project, member=other_user, is_active=True
        ).exists()
        check(
            "mención → Notification (solo con acceso al canal)",
            (notif is not None) == bool(expected),
            f"notif={'sí' if notif else 'no'} acceso={'sí' if expected else 'no'}",
        )
        if notif:
            notif.delete(soft=False)
    else:
        print("  (sin segundo usuario — saltado)")

    print("\nPERMISOS")
    outsider = (
        User.objects.exclude(
            id__in=WorkspaceMember.objects.filter(workspace=ws, is_active=True).values_list(
                "member_id", flat=True
            )
        )
        .filter(is_active=True, is_bot=False)
        .first()
    )
    if outsider:
        c3 = Client()
        c3.force_login(outsider)
        r = c3.get(f"{base}/channels/")
        check("no-miembro del workspace → 403", r.status_code == 403, f"HTTP {r.status_code}")
        r = c3.get(f"{base}/channels/{ch}/messages/")
        check("no-miembro no lee mensajes", r.status_code in (403, 404), f"HTTP {r.status_code}")
    else:
        print("  (no hay usuario fuera del workspace — saltado)")

finally:
    print("\nLIMPIEZA")
    for cid in created_channels:
        row = Channel.objects.filter(pk=cid).first()
        if row:
            row.delete(soft=False)
    # Notificaciones y membership residuales de los canales borrados.
    Notification.objects.filter(entity_name="chat_message").filter(
        data__channel__id__in=created_channels
    ).delete(soft=False)
    ChannelMember.objects.filter(channel_id__in=created_channels).delete(soft=False)
    if not general_existed:
        g = Channel.objects.filter(project=project, is_general=True).first()
        if g:
            g.delete(soft=False)
    print("  hecho")

total, passed = len(results), sum(results)
print(f"\n{passed}/{total} checks")
raise SystemExit(0 if passed == total else 1)
