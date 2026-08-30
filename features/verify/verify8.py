"""Prueba funcional del rol de cobranza y la gestión de acceso por miembro.
Corre dentro del contenedor api. No deja datos."""

import json
import os
from datetime import date, timedelta

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "plane.settings.production")
django.setup()

from django.test import Client  # noqa: E402
from plane.db.models import ProjectMember, Workspace, WorkspaceMember  # noqa: E402
from plane.finance.models import FinanceAccess, FinanceProfile, Invoice, Payment  # noqa: E402

OK, FAIL = "\033[92mOK\033[0m", "\033[91mFALLO\033[0m"
results = []
J = "application/json"


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(f"  {OK if cond else FAIL}  {name}" + (f" — {detail}" if detail else ""))


ws = Workspace.objects.first()
slug = ws.slug
admin = WorkspaceMember.objects.filter(workspace=ws, role=20, is_active=True).first().member
member = (
    WorkspaceMember.objects.filter(workspace=ws, is_active=True)
    .exclude(role=20)
    .first()
    .member
)
pm = ProjectMember.objects.filter(member=admin, is_active=True, role=20).select_related("project").first()
project = pm.project

ca = Client(); ca.force_login(admin)
cm = Client(); cm.force_login(member)
base = f"/api/workspaces/{slug}/finance"
today = date.today()

cleanup = {"invoices": [], "payments": [], "access_member": member.id, "profile_created": False}
if not FinanceProfile.objects.filter(project=project).exists():
    FinanceProfile.objects.get_or_create(project=project, defaults={"workspace_id": ws.id})
    cleanup["profile_created"] = True
access_before = FinanceAccess.objects.filter(workspace=ws, member=member).first()
role_before = access_before.role if access_before else None
try:
    print("GESTIÓN DE ACCESO POR MIEMBRO (upsert)")
    r = cm.post(f"{base}/access/", data=json.dumps({"member_id": str(member.id), "role": "finance"}), content_type=J)
    check("miembro sin admin no gestiona acceso → 403", r.status_code == 403, f"HTTP {r.status_code}")
    r = ca.post(f"{base}/access/", data=json.dumps({"member_id": str(member.id), "role": "sultan"}), content_type=J)
    check("rol inválido → 400", r.status_code == 400, f"HTTP {r.status_code}")
    r = ca.post(f"{base}/access/", data=json.dumps({"member_id": str(member.id), "role": "collections"}), content_type=J)
    check("asignar cobranza (upsert)", r.status_code in (200, 201) and r.json().get("role") == "collections", f"HTTP {r.status_code}")

    print("\nALCANCE DEL ROL COBRANZA")
    r = cm.get(f"{base}/me/")
    me = r.json()
    check("me/: sin acceso completo, con cobranza", me.get("has_access") is False and me.get("has_collections") is True and me.get("role") == "collections", str(me))
    for path, name in [("dashboard/", "dashboard"), ("pnl/", "pnl"), ("expenses/", "gastos"), ("analyses/", "análisis")]:
        r = cm.get(f"{base}/{path}")
        check(f"cobranza NO ve {name} → 403", r.status_code == 403, f"HTTP {r.status_code}")

    # un cobro pendiente para trabajar
    inv = Invoice.objects.create(
        project=project, workspace=ws, concept="Cobro verify8", amount="1500.00",
        currency="MXN", issue_date=today - timedelta(days=20), due_date=today - timedelta(days=5),
        status="pending",
    )
    cleanup["invoices"].append(inv.id)
    r = cm.get(f"{base}/collections/")
    rows = r.json().get("invoices", [])
    mine = next((x for x in rows if x["id"] == str(inv.id)), None)
    check("cobranza ve la lista de cobros", r.status_code == 200 and mine is not None, f"HTTP {r.status_code}")
    check("cobro vencido marcado overdue con días", mine and mine["status"] == "overdue" and mine["days"] == 5, str(mine and (mine["status"], mine["days"])))
    check("la lista no expone datos de cliente/revenue", mine and "revenue" not in mine and "rfc" not in mine)

    print("\nREGISTRO DE PAGOS (cobranza)")
    r = cm.post(f"{base}/collections/{inv.id}/payments/", data=json.dumps({"amount": "500.00", "paid_at": today.isoformat(), "method": "transfer", "reference": "SPEI-1"}), content_type=J)
    check("pago parcial registrado", r.status_code == 201, f"HTTP {r.status_code} {r.json()}")
    if r.status_code == 201:
        cleanup["payments"].append(r.json()["id"])
    r = cm.get(f"{base}/collections/")
    mine = next((x for x in r.json()["invoices"] if x["id"] == str(inv.id)), None)
    check("restante actualizado", mine and abs(mine["remaining"] - 1000.0) < 0.01, str(mine and mine["remaining"]))
    r = cm.post(f"{base}/collections/{inv.id}/payments/", data=json.dumps({"amount": "-5", "paid_at": today.isoformat()}), content_type=J)
    check("monto negativo → 400", r.status_code == 400, f"HTTP {r.status_code}")
    r = cm.post(f"{base}/collections/{inv.id}/payments/", data=json.dumps({"amount": "1000.00", "paid_at": today.isoformat()}), content_type=J)
    if r.status_code == 201:
        cleanup["payments"].append(r.json()["id"])
    inv.refresh_from_db()
    check("cubierto por completo → cobro pagado", r.status_code == 201 and inv.status == "paid", inv.status)
    r = cm.post(f"{base}/collections/{inv.id}/payments/", data=json.dumps({"amount": "1.00", "paid_at": today.isoformat()}), content_type=J)
    check("cobro ya pagado rechaza más pagos → 400", r.status_code == 400, f"HTTP {r.status_code}")
    r = cm.get(f"{base}/collections/")
    check("pagado desaparece de la lista", all(x["id"] != str(inv.id) for x in r.json()["invoices"]))

    print("\nCAMBIO Y RETIRO DE ROL")
    r = ca.post(f"{base}/access/", data=json.dumps({"member_id": str(member.id), "role": "finance"}), content_type=J)
    check("subir a financiero (upsert sobre fila existente)", r.status_code == 200 and r.json().get("role") == "finance", f"HTTP {r.status_code}")
    r = cm.get(f"{base}/dashboard/")
    check("financiero ya ve el dashboard", r.status_code == 200, f"HTTP {r.status_code}")
    r = ca.post(f"{base}/access/", data=json.dumps({"member_id": str(member.id), "role": "none"}), content_type=J)
    check("retirar acceso (role=none)", r.status_code == 204, f"HTTP {r.status_code}")
    r = cm.get(f"{base}/collections/")
    check("sin rol → 403 en cobranza", r.status_code == 403, f"HTTP {r.status_code}")
    r = ca.get(f"{base}/access/")
    check("lista de acceso lleva role", r.status_code == 200 and all("role" in x for x in r.json()))

    print("\nADMIN CONSERVA TODO")
    r = ca.get(f"{base}/collections/")
    check("admin también ve cobranza", r.status_code == 200, f"HTTP {r.status_code}")
    r = ca.get(f"{base}/me/")
    check("me/ de admin: role=admin y ambos flags", r.json().get("role") == "admin" and r.json().get("has_access") and r.json().get("has_collections"))

finally:
    print("\nLIMPIEZA")
    Payment.objects.filter(pk__in=cleanup["payments"]).delete()
    Invoice.objects.filter(pk__in=cleanup["invoices"]).delete()
    for row in FinanceAccess.objects.filter(workspace=ws, member_id=cleanup["access_member"]):
        row.delete(soft=False)
    if role_before is not None:
        row = FinanceAccess(workspace=ws, member_id=cleanup["access_member"], role=role_before)
        row.save(created_by_id=str(admin.id))
    if cleanup["profile_created"]:
        for row in FinanceProfile.objects.filter(project=project):
            row.delete(soft=False)
    print("  hecho")

total, passed = len(results), sum(results)
print(f"\n{'✅' if passed == total else '❌'} {passed}/{total}")
raise SystemExit(0 if passed == total else 1)
