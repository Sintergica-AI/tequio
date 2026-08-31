"""Prueba funcional del chat v2: DMs (canónicos y privados), canales privados
con roster, pins, búsqueda y presign de adjuntos. Corre dentro del contenedor
api. No deja datos."""

import json
import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "plane.settings.production")
django.setup()

from django.test import Client  # noqa: E402
from plane.chat.models import Channel, ChannelMember  # noqa: E402
from plane.db.models import FileAsset, ProjectMember, Workspace, WorkspaceMember  # noqa: E402

OK, FAIL = "\033[92mOK\033[0m", "\033[91mFALLO\033[0m"
results = []
J = "application/json"
MARK = "verify12-tmp"


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(f"  {OK if cond else FAIL}  {name}" + (f" — {detail}" if detail else ""))


ws = Workspace.objects.first()
slug = ws.slug
admin = WorkspaceMember.objects.filter(workspace=ws, role=20, is_active=True).first().member
other = (
    WorkspaceMember.objects.filter(workspace=ws, is_active=True)
    .exclude(member=admin)
    .select_related("member")
    .first()
)
other_user = other.member if other else None
third = (
    WorkspaceMember.objects.filter(workspace=ws, is_active=True)
    .exclude(member__in=[admin] + ([other_user] if other_user else []))
    .select_related("member")
    .first()
)
third_user = third.member if third else None

c = Client()
c.force_login(admin)
base = f"/api/workspaces/{slug}/chat"
created_channels = []

try:
    if not other_user:
        print("FATAL: se necesita un segundo usuario en el workspace")
        raise SystemExit(1)

    print("DMS")
    r = c.post(f"{base}/dms/", data=json.dumps({"member_ids": [str(other_user.id)]}), content_type=J)
    check("abrir DM", r.status_code == 201 and r.json()["is_direct"] is True)
    dm = r.json()
    created_channels.append(dm["id"])
    r = c.post(f"{base}/dms/", data=json.dumps({"member_ids": [str(other_user.id)]}), content_type=J)
    check("reabrir devuelve el MISMO canal", r.status_code == 201 and r.json()["id"] == dm["id"])
    check("member_ids expuestos", set(dm["member_ids"]) == {str(admin.id), str(other_user.id)})
    r = c.post(f"{base}/dms/", data=json.dumps({"member_ids": []}), content_type=J)
    check("DM sin gente → 400", r.status_code == 400, f"HTTP {r.status_code}")
    r = c.patch(f"{base}/channels/{dm['id']}/", data=json.dumps({"name": "x"}), content_type=J)
    check("DM no se edita", r.status_code == 400, f"HTTP {r.status_code}")
    r = c.post(
        f"{base}/channels/{dm['id']}/messages/",
        data=json.dumps({"message_html": "<p>hola dm</p>"}),
        content_type=J,
    )
    check("mensaje en DM", r.status_code == 201)

    if third_user:
        c3 = Client()
        c3.force_login(third_user)
        r = c3.get(f"{base}/channels/{dm['id']}/messages/")
        check("tercero NO ve el DM → 404", r.status_code == 404, f"HTTP {r.status_code}")
        r = c3.get(f"{base}/channels/")
        ids = [row["id"] for row in r.json()]
        check("DM fuera de la lista del tercero", dm["id"] not in ids)
    else:
        print("  (sin tercer usuario — visibilidad de DM saltada)")

    print("\nCANAL PRIVADO")
    r = c.post(
        f"{base}/channels/",
        data=json.dumps({"name": f"{MARK}-priv", "access": 1, "member_ids": [str(other_user.id)]}),
        content_type=J,
    )
    check("crear privado con invitado", r.status_code == 201 and r.json()["access"] == 1)
    priv = r.json()
    created_channels.append(priv["id"])
    check("roster inicial = creador + invitado", set(priv["member_ids"]) == {str(admin.id), str(other_user.id)})

    r = c.get(f"{base}/channels/{priv['id']}/members/")
    check("GET members", r.status_code == 200 and len(r.json()) == 2)

    if third_user:
        c3 = Client()
        c3.force_login(third_user)
        r = c3.get(f"{base}/channels/{priv['id']}/messages/")
        check("no-miembro NO ve el privado → 404", r.status_code == 404, f"HTTP {r.status_code}")
        r = c.post(
            f"{base}/channels/{priv['id']}/members/",
            data=json.dumps({"member_ids": [str(third_user.id)]}),
            content_type=J,
        )
        check("invitar al tercero", r.status_code == 200)
        r = c3.get(f"{base}/channels/{priv['id']}/messages/")
        check("ya-miembro SÍ ve el privado", r.status_code == 200, f"HTTP {r.status_code}")
        r = c3.delete(f"{base}/channels/{priv['id']}/members/{third_user.id}/")
        check("salir del canal (self)", r.status_code == 204, f"HTTP {r.status_code}")
        r = c3.get(f"{base}/channels/{priv['id']}/messages/")
        check("tras salir vuelve el 404", r.status_code == 404, f"HTTP {r.status_code}")
    else:
        print("  (sin tercer usuario — roster dinámico saltado)")

    print("\nPINS")
    r = c.post(
        f"{base}/channels/{priv['id']}/messages/",
        data=json.dumps({"message_html": "<p>mensaje fijable único vf12</p>"}),
        content_type=J,
    )
    mid = r.json()["id"]
    r = c.post(f"{base}/channels/{priv['id']}/messages/{mid}/pin/", data="{}", content_type=J)
    check("fijar", r.status_code == 200 and r.json()["pinned_at"])
    r = c.get(f"{base}/channels/{priv['id']}/pins/")
    check("lista de fijados", r.status_code == 200 and any(m["id"] == mid for m in r.json()))
    r = c.delete(f"{base}/channels/{priv['id']}/messages/{mid}/pin/")
    ok_unpin = r.status_code == 204
    r = c.get(f"{base}/channels/{priv['id']}/pins/")
    check("desfijar", ok_unpin and not any(m["id"] == mid for m in r.json()))

    print("\nANCLA (salto desde búsqueda)")
    # ancla sobre el mensaje fijable: la página debe terminar en él e incluirlo
    r = c.get(f"{base}/channels/{priv['id']}/messages/?anchor={mid}")
    ok_anchor = r.status_code == 200 and any(m["id"] == mid for m in r.json()["results"])
    check("ventana anclada incluye el mensaje", ok_anchor, f"HTTP {r.status_code}")
    check("ancla de raíz no es reply", r.status_code == 200 and r.json().get("anchor_is_reply") is False)
    r = c.post(
        f"{base}/channels/{priv['id']}/messages/",
        data=json.dumps({"message_html": "<p>respuesta ancla</p>", "parent_id": mid}),
        content_type=J,
    )
    reply_id = r.json()["id"]
    r = c.get(f"{base}/channels/{priv['id']}/messages/?anchor={reply_id}")
    check(
        "ancla de reply apunta a su raíz",
        r.status_code == 200
        and r.json().get("anchor_is_reply") is True
        and r.json().get("anchor_root_id") == mid,
    )
    r = c.get(f"{base}/channels/{priv['id']}/messages/?anchor=00000000-0000-0000-0000-000000000000")
    check("ancla inexistente → 404", r.status_code == 404, f"HTTP {r.status_code}")

    # paginación hacia el presente (?after=): desde el ancla, el resto de raíces
    from urllib.parse import quote as _q

    from plane.chat.models import ChatMessage as _CM

    anchor_msg = _CM.objects.get(pk=mid)
    r = c.get(
        f"{base}/channels/{priv['id']}/messages/?after={_q(f'{anchor_msg.created_at.isoformat()},{mid}')}"
    )
    check(
        "after devuelve solo raíces más nuevas, asc",
        r.status_code == 200
        and all(m["created_at"] > anchor_msg.created_at.isoformat() for m in r.json()["results"])
        and r.json()["has_more"] is False,
    )
    r = c.get(f"{base}/channels/{priv['id']}/messages/?after=basura")
    check("after inválido → 400", r.status_code == 400, f"HTTP {r.status_code}")

    print("\nBÚSQUEDA")
    r = c.get(f"{base}/search/?q=fijable único vf12")
    check("busca en visibles", r.status_code == 200 and any(x["id"] == mid for x in r.json()))
    r = c.get(f"{base}/search/?q=a")
    check("query corta → 400", r.status_code == 400, f"HTTP {r.status_code}")
    if third_user:
        c3 = Client()
        c3.force_login(third_user)
        r = c3.get(f"{base}/search/?q=fijable único vf12")
        check("privado invisible en búsqueda ajena", r.status_code == 200 and not any(x["id"] == mid for x in r.json()))

    print("\nADJUNTOS")
    r = c.post(
        f"{base}/channels/{priv['id']}/assets/",
        data=json.dumps({"name": "foto.png", "type": "image/png", "size": 1024}),
        content_type=J,
    )
    ok_presign = r.status_code == 200 and r.json().get("asset_id") and r.json().get("upload_data")
    check("presign de adjunto", ok_presign, f"HTTP {r.status_code}")
    asset_id = r.json().get("asset_id") if ok_presign else None
    if asset_id:
        r = c.patch(f"{base}/channels/{priv['id']}/assets/{asset_id}/", data="{}", content_type=J)
        check("confirmar subida", r.status_code == 200)
        r = c.post(
            f"{base}/channels/{priv['id']}/assets/",
            data=json.dumps({"name": "grande.bin", "type": "application/octet-stream", "size": 999999999}),
            content_type=J,
        )
        check("límite de tamaño → 400", r.status_code == 400, f"HTTP {r.status_code}")

    print("\nUNREADS CON MUTE")
    r = c.get(f"{base}/unreads/")
    check("unreads incluye is_muted", r.status_code == 200 and all("is_muted" in row for row in r.json()))

finally:
    print("\nLIMPIEZA")
    FileAsset.objects.filter(
        entity_type="CHAT", attributes__channel_id__in=[str(x) for x in created_channels]
    ).delete(soft=False)
    for cid in created_channels:
        row = Channel.objects.filter(pk=cid).first()
        if row:
            row.delete(soft=False)
    ChannelMember.objects.filter(channel_id__in=created_channels).delete(soft=False)
    print("  hecho")

total, passed = len(results), sum(results)
print(f"\n{passed}/{total} checks")
raise SystemExit(0 if passed == total else 1)
