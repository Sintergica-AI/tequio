"""Prueba funcional del centro de mando: gastos, caja, P&L, forecast, insights.
Corre dentro del contenedor api. No deja datos."""

import json
import os
from datetime import date, timedelta

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "plane.settings.production")
django.setup()

from django.test import Client  # noqa: E402
from plane.db.models import ProjectMember, Workspace, WorkspaceMember  # noqa: E402
from plane.finance.models import (  # noqa: E402
    CashSnapshot, Contract, ExpenseEntry, FinanceProfile, Invoice, Payment,
)

OK, FAIL = "\033[92mOK\033[0m", "\033[91mFALLO\033[0m"
results = []
J = "application/json"


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(f"  {OK if cond else FAIL}  {name}" + (f" — {detail}" if detail else ""))


ws = Workspace.objects.first()
slug = ws.slug
admin = WorkspaceMember.objects.filter(workspace=ws, role=20, is_active=True).first().member
pm = ProjectMember.objects.filter(member=admin, is_active=True, role=20).select_related("project").first()
project = pm.project
c = Client(); c.force_login(admin)
base = f"/api/workspaces/{slug}/finance"
pbase = f"/api/workspaces/{slug}/projects/{project.id}/finance"
today = date.today()
this_month = f"{today.year:04d}-{today.month:02d}"
ly, lm = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
last_month = f"{ly:04d}-{lm:02d}"

created_local = []
try:
    print("GASTOS")
    r = c.post(f"{base}/expenses/", data=json.dumps({"month": last_month, "category": "payroll", "concept": "Nómina", "amount": "40000.00", "currency": "MXN"}), content_type=J)
    check("registrar gasto", r.status_code == 201, f"HTTP {r.status_code}")
    exp_id = r.json().get("id")
    r = c.post(f"{base}/expenses/", data=json.dumps({"month": "2026-13", "category": "other", "concept": "x", "amount": "1", "currency": "MXN"}), content_type=J)
    check("mes inválido → 400", r.status_code == 400, f"HTTP {r.status_code}")
    r = c.get(f"{base}/expenses/?month={last_month}")
    check("filtrar por mes", r.status_code == 200 and any(e["id"] == exp_id for e in r.json()))

    print("\nCAJA")
    r = c.post(f"{base}/cash/", data=json.dumps({"as_of": today.isoformat(), "amount": "250000.00", "currency": "MXN"}), content_type=J)
    check("registrar saldo", r.status_code == 201, f"HTTP {r.status_code}")
    cash_id = r.json().get("id")

    print("\nP&L")
    r = c.get(f"{base}/pnl/")
    check("pnl 200", r.status_code == 200, f"HTTP {r.status_code}")
    row = next((m for m in r.json()["months"] if m["month"] == last_month), None)
    check("gasto reflejado en el mes", row and abs(row["MXN"]["expenses"] - 40000.0) < 0.01, str(row["MXN"] if row else None))
    check("net = income - expenses", row and abs(row["MXN"]["net"] - (row["MXN"]["income"] - 40000.0)) < 0.01)

    print("\nFORECAST")
    r = c.get(f"{base}/forecast/")
    f = r.json()
    check("forecast 200", r.status_code == 200, f"HTTP {r.status_code}")
    check("6 meses proyectados", len(f["months"]) == 6)
    check("caja anclada al snapshot", f["cash"]["MXN"] and abs(f["cash"]["MXN"]["amount"] - 250000.0) < 0.01)
    check("gasto promedio > 0", f["expense_run_rate"]["MXN"] > 0, str(f["expense_run_rate"]))
    rw = f["runway_months"]["MXN"]
    check("runway calculado (número o infinito)", isinstance(rw, (int, float)) or rw == "infinite", str(rw))
    m0 = f["months"][0]["MXN"]
    check("caja proyectada acumula el neto", m0["projected_cash"] is not None and abs(m0["projected_cash"] - (250000.0 + m0["net"])) < 0.01)

    print("\nINSIGHTS")
    r = c.get(f"{base}/insights/")
    kinds = [i["kind"] for i in r.json()["insights"]]
    check("insights 200", r.status_code == 200, f"HTTP {r.status_code}")
    check("cobranza vencida detectada", "overdue_collection" in kinds, str(kinds))
    check("ya no pide snapshot de caja", "no_cash_snapshot" not in kinds)
    check("ya no pide gastos del mes pasado", "missing_expenses" not in kinds)
    sev = {i["kind"]: i["severity"] for i in r.json()["insights"]}
    check("cobranza es crítica", sev.get("overdue_collection") == "critical")

    print("\nLIMPIEZA VÍA API")
    r = c.delete(f"{base}/expenses/{exp_id}/")
    check("eliminar gasto", r.status_code == 204, f"HTTP {r.status_code}")
    r = c.delete(f"{base}/cash/{cash_id}/")
    check("eliminar saldo", r.status_code == 204, f"HTTP {r.status_code}")
finally:
    ExpenseEntry.all_objects.filter(workspace=ws).delete()
    CashSnapshot.all_objects.filter(workspace=ws).delete()
    print("\n(datos de prueba eliminados)")

print("=" * 52)
print(f"RESULTADO: {sum(results)}/{len(results)} comprobaciones correctas")
print("=" * 52)
