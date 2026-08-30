"""Prueba funcional: los admins ya NO tienen acceso financiero implícito.
La migración 0005 siembra filas explícitas para los admins existentes; un
admin sin fila gestiona la allowlist pero no ve datos. Corre dentro del
contenedor api. No deja datos."""

import json
import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "plane.settings.production")
django.setup()

from django.test import Client  # noqa: E402
from plane.db.models import Workspace, WorkspaceMember  # noqa: E402
from plane.finance.models import FinanceAccess  # noqa: E402

OK, FAIL = "\033[92mOK\033[0m", "\033[91mFALLO\033[0m"
results = []
J = "application/json"


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(f"  {OK if cond else FAIL}  {name}" + (f" — {detail}" if detail else ""))


ws = Workspace.objects.first()
slug = ws.slug
admins = [wm.member for wm in WorkspaceMember.objects.filter(workspace=ws, role=20, is_active=True)]
admin = admins[0]
member = WorkspaceMember.objects.filter(workspace=ws, is_active=True).exclude(role=20).first().member

ca = Client(); ca.force_login(admin)
cm = Client(); cm.force_login(member)
base = f"/api/workspaces/{slug}/finance"

row_before = FinanceAccess.objects.filter(workspace=ws, member=admin).first()
role_before = row_before.role if row_before else None
try:
    print("MIGRACIÓN 0005: ADMINS SEMBRADOS")
    seeded = {
        str(a.id): FinanceAccess.objects.filter(workspace=ws, member=a).first() for a in admins
    }
    check(
        "todos los admins activos tienen fila explícita",
        all(r is not None for r in seeded.values()),
        str({k: (r.role if r else None) for k, r in seeded.items()}),
    )
    check("las filas sembradas son rol financiero", all(r and r.role == "finance" for r in seeded.values()))
    r = ca.get(f"{base}/me/")
    me = r.json()
    check("admin sembrado: has_access por su fila, no implícito", me.get("has_access") is True and me.get("role") == "finance" and me.get("is_admin") is True, str(me))
    r = ca.get(f"{base}/dashboard/")
    check("admin sembrado ve el dashboard", r.status_code == 200, f"HTTP {r.status_code}")

    print("\nADMIN SIN ACCESO FINANCIERO")
    r = ca.post(f"{base}/access/", data=json.dumps({"member_id": str(admin.id), "role": "none"}), content_type=J)
    check("el admin puede retirarse su propio rol", r.status_code == 204, f"HTTP {r.status_code}")
    r = ca.get(f"{base}/me/")
    me = r.json()
    check("me/: is_admin true pero sin acceso ni cobranza", me.get("is_admin") is True and me.get("has_access") is False and me.get("has_collections") is False and me.get("role") is None, str(me))
    for path, name in [("dashboard/", "dashboard"), ("collections/", "cobranza"), ("pnl/", "pnl"), ("analyses/", "análisis")]:
        r = ca.get(f"{base}/{path}")
        check(f"admin sin rol NO ve {name} → 403", r.status_code == 403, f"HTTP {r.status_code}")
    r = ca.get(f"{base}/access/")
    check("pero SÍ gestiona la allowlist (GET access)", r.status_code == 200, f"HTTP {r.status_code}")
    r = ca.post(f"{base}/access/", data=json.dumps({"member_id": str(member.id), "role": "collections"}), content_type=J)
    check("y asigna roles a otros", r.status_code in (200, 201), f"HTTP {r.status_code}")
    ca.post(f"{base}/access/", data=json.dumps({"member_id": str(member.id), "role": "none"}), content_type=J)

    print("\nRECUPERACIÓN")
    r = ca.post(f"{base}/access/", data=json.dumps({"member_id": str(admin.id), "role": "finance"}), content_type=J)
    check("el admin se reasigna el rol financiero", r.status_code in (200, 201), f"HTTP {r.status_code}")
    r = ca.get(f"{base}/dashboard/")
    check("y recupera el dashboard", r.status_code == 200, f"HTTP {r.status_code}")

    print("\nMIEMBRO NORMAL SIN CAMBIOS")
    r = cm.get(f"{base}/me/")
    me = r.json()
    check("miembro sin rol: sin acceso, is_admin false", me.get("has_access") is False and me.get("is_admin") is False, str(me))
    r = cm.get(f"{base}/access/")
    check("miembro no gestiona allowlist → 403", r.status_code == 403, f"HTTP {r.status_code}")

finally:
    print("\nLIMPIEZA")
    # dejar al admin exactamente como estaba antes de la prueba
    current = FinanceAccess.objects.filter(workspace=ws, member=admin).first()
    if role_before is None and current is not None:
        current.delete(soft=False)
    elif role_before is not None:
        if current is None:
            row = FinanceAccess(workspace=ws, member=admin, role=role_before)
            row.save(created_by_id=str(admin.id))
        elif current.role != role_before:
            current.role = role_before
            current.save(update_fields=["role", "updated_at"])
    print("  hecho")

total, passed = len(results), sum(results)
print(f"\n{'✅' if passed == total else '❌'} {passed}/{total}")
raise SystemExit(0 if passed == total else 1)
