"""Prueba funcional del módulo de finanzas. Corre dentro del contenedor api.
No deja datos: borra (hard) todo lo que crea."""

import json
import os
from datetime import date, timedelta

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "plane.settings.production")
django.setup()

from django.test import Client  # noqa: E402
from plane.db.models import ProjectMember, Workspace, WorkspaceMember  # noqa: E402
from plane.finance.models import (  # noqa: E402
    Contract,
    FinanceAccess,
    FinanceProfile,
    Invoice,
    Payment,
)

OK, FAIL = "\033[92mOK\033[0m", "\033[91mFALLO\033[0m"
results = []
J = "application/json"


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(f"  {OK if cond else FAIL}  {name}" + (f" — {detail}" if detail else ""))


ws = Workspace.objects.first()
slug = ws.slug
admin = WorkspaceMember.objects.filter(workspace=ws, role=20, is_active=True).select_related("member").first().member
plain = (
    WorkspaceMember.objects.filter(workspace=ws, role__lt=20, is_active=True)
    .exclude(member=admin)
    .select_related("member")
    .first()
)
pm = ProjectMember.objects.filter(member=admin, is_active=True, role=20).select_related("project").first()
project = pm.project

ca, cp = Client(), Client()
ca.force_login(admin)
if plain:
    cp.force_login(plain.member)
base = f"/api/workspaces/{slug}/finance"
pbase = f"/api/workspaces/{slug}/projects/{project.id}/finance"

today = date.today()

try:
    print("ACCESO")
    r = ca.get(f"{base}/me/")
    check("admin: me → has_access + is_admin", r.status_code == 200 and r.json() == {"has_access": True, "is_admin": True})
    if plain:
        r = cp.get(f"{base}/me/")
        check("miembro sin allowlist: has_access false", r.status_code == 200 and r.json()["has_access"] is False)
        r = cp.get(f"{base}/dashboard/")
        check("miembro sin allowlist: dashboard 403", r.status_code == 403, f"HTTP {r.status_code}")
        r = cp.get(f"{pbase}/contracts/")
        check("miembro sin allowlist: contratos 403", r.status_code == 403, f"HTTP {r.status_code}")
        # alta en allowlist
        r = ca.post(f"{base}/access/", data=json.dumps({"member_ids": [str(plain.member_id)]}), content_type=J)
        check("admin da acceso", r.status_code == 201, f"HTTP {r.status_code}")
        access_id = r.json()[0]["id"] if r.status_code == 201 else None
        r = cp.get(f"{base}/dashboard/")
        check("con allowlist: dashboard 200", r.status_code == 200, f"HTTP {r.status_code}")
        r = cp.post(f"{base}/access/", data=json.dumps({"member_ids": [str(plain.member_id)]}), content_type=J)
        check("con allowlist: gestionar acceso sigue siendo 403", r.status_code == 403, f"HTTP {r.status_code}")
        if access_id:
            r = ca.delete(f"{base}/access/{access_id}/")
            check("admin quita acceso", r.status_code == 204, f"HTTP {r.status_code}")
            r = cp.get(f"{base}/dashboard/")
            check("sin allowlist otra vez: 403", r.status_code == 403, f"HTTP {r.status_code}")
    else:
        print("  (no hay un miembro no-admin para probar la allowlist)")

    print("\nPERFIL (cliente)")
    r = ca.post(f"{pbase}/profile/", data=json.dumps({"default_currency": "MXN", "billing_day": 5}), content_type=J)
    check("crear perfil", r.status_code == 201, f"HTTP {r.status_code}")
    r = ca.post(f"{pbase}/profile/", data=json.dumps({}), content_type=J)
    check("perfil duplicado rechazado", r.status_code == 400, f"HTTP {r.status_code}")
    r = ca.get(f"{base}/dashboard/")
    check("el proyecto aparece como cliente", any(c["project_id"] == str(project.id) for c in r.json()["clients"]))

    print("\nIGUALA (retainer) — generación perezosa")
    start = (today.replace(day=1) - timedelta(days=40)).replace(day=1)  # hace ~2 meses
    r = ca.post(
        f"{pbase}/contracts/",
        data=json.dumps({
            "name": "Iguala prueba", "kind": "retainer", "amount": "15000.00", "currency": "MXN",
            "start_date": start.isoformat(), "billing_cycle": "monthly", "payment_terms_days": 10,
        }),
        content_type=J,
    )
    check("crear contrato retainer", r.status_code == 201, f"HTTP {r.status_code}")
    r = ca.get(f"{pbase}/invoices/")
    autos = [i for i in r.json() if i["period_key"]]
    check("cobros auto-generados (≥2 periodos)", len(autos) >= 2, f"{len(autos)} generados")
    n1 = len(r.json())
    r = ca.get(f"{pbase}/invoices/")
    check("idempotente: segundo GET no duplica", len(r.json()) == n1)
    check("monto y moneda del contrato", autos and autos[0]["amount"] == "15000.00" and autos[0]["currency"] == "MXN")

    print("\nCOBRO ÚNICO USD + PAGO PARCIAL")
    r = ca.post(
        f"{pbase}/invoices/",
        data=json.dumps({
            "concept": "Desarrollo extra", "amount": "1000.00", "currency": "USD",
            "issue_date": today.isoformat(), "due_date": (today + timedelta(days=15)).isoformat(),
        }),
        content_type=J,
    )
    check("crear cobro manual USD", r.status_code == 201, f"HTTP {r.status_code}")
    inv_usd = r.json()["id"]
    r = ca.post(
        f"{pbase}/payments/",
        data=json.dumps({"invoice": inv_usd, "amount": "400.00", "currency": "USD", "paid_at": today.isoformat()}),
        content_type=J,
    )
    check("pago parcial", r.status_code == 201, f"HTTP {r.status_code}")
    r = ca.get(f"{pbase}/invoices/{inv_usd}/")
    check("effective_status = partial", r.json().get("effective_status") == "partial", r.json().get("effective_status"))
    r = ca.get(f"{pbase}/summary/")
    s = r.json()
    check("outstanding USD = 600", abs(s["outstanding"]["USD"] - 600.0) < 0.01, str(s["outstanding"]))
    check("revenue USD = 400, sin mezclar con MXN", abs(s["revenue"]["USD"] - 400.0) < 0.01 and s["revenue"]["MXN"] == 0.0)

    print("\nALERTAS")
    r = ca.get(f"{base}/dashboard/")
    d = r.json()
    overdue = [a for a in d["alerts"] if a["type"] == "overdue" and a["project_id"] == str(project.id)]
    check("cobros de iguala vencidos aparecen como alerta", len(overdue) >= 1, f"{len(overdue)} vencidos")
    cli = next(c for c in d["clients"] if c["project_id"] == str(project.id))
    check("estado del cliente: vencido", cli["status"] == "vencido", cli["status"])
    check("retainer activo visible", cli["active_retainer"] and cli["active_retainer"]["amount"] == 15000.0)
    check("totales por moneda separados", "MXN" in d["totals"] and "USD" in d["totals"])
    r = ca.post(
        f"{pbase}/invoices/",
        data=json.dumps({
            "concept": "Próximo", "amount": "500.00", "currency": "MXN",
            "issue_date": today.isoformat(), "due_date": (today + timedelta(days=3)).isoformat(),
        }),
        content_type=J,
    )
    inv_soon = r.json()["id"]
    r = ca.get(f"{base}/dashboard/")
    upc = [a for a in r.json()["alerts"] if a["type"] == "upcoming" and a["invoice_id"] == inv_soon]
    check("cobro a 3 días aparece como próximo", len(upc) == 1)

    print("\nVALIDACIONES")
    r = ca.post(
        f"{pbase}/payments/",
        data=json.dumps({"invoice": inv_usd, "amount": "100.00", "currency": "MXN", "paid_at": today.isoformat()}),
        content_type=J,
    )
    check("pago con moneda distinta al cobro → 400", r.status_code == 400, f"HTTP {r.status_code}")
    r = ca.post(
        f"{pbase}/contracts/",
        data=json.dumps({
            "name": "x", "kind": "retainer", "amount": "-5", "currency": "MXN",
            "start_date": today.isoformat(), "billing_cycle": "monthly",
        }),
        content_type=J,
    )
    check("monto negativo → 400", r.status_code == 400, f"HTTP {r.status_code}")

    print("\nPAGO COMPLETO MARCA EL COBRO COMO PAGADO")
    r = ca.post(
        f"{pbase}/payments/",
        data=json.dumps({"invoice": inv_soon, "amount": "500.00", "currency": "MXN", "paid_at": today.isoformat()}),
        content_type=J,
    )
    check("pago completo", r.status_code == 201, f"HTTP {r.status_code}")
    r = ca.get(f"{pbase}/invoices/{inv_soon}/")
    check("status = paid al cubrirse", r.json().get("status") == "paid", r.json().get("status"))

finally:
    Payment.all_objects.filter(project=project).delete()
    Invoice.all_objects.filter(project=project).delete()
    Contract.all_objects.filter(project=project).delete()
    FinanceProfile.all_objects.filter(project=project).delete()
    FinanceAccess.all_objects.filter(workspace=ws).delete()
    print("\n(datos de prueba eliminados)")

print("=" * 52)
print(f"RESULTADO: {sum(results)}/{len(results)} comprobaciones correctas")
print("=" * 52)
