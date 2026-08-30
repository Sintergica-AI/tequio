"""Prueba funcional de la ronda "clientes y fiscal": datos fiscales del perfil,
CSF (presign/confirm/redirect), colores de cliente, análisis guardados y
filtros por rango de fechas. Corre dentro del contenedor api. No deja datos."""

import json
import os
from datetime import date, timedelta

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "plane.settings.production")
django.setup()

from django.test import Client  # noqa: E402
from plane.db.models import FileAsset, ProjectMember, Workspace, WorkspaceMember  # noqa: E402
from plane.finance.models import (  # noqa: E402
    ExpenseEntry, FinanceAnalysis, FinanceProfile, Payment,
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

cleanup = {"payments": [], "expenses": [], "analyses": [], "assets": [], "profile_created": False}
profile_before = FinanceProfile.objects.filter(project=project).first()
fiscal_before = None
try:
    print("PERFIL FISCAL")
    if profile_before:
        fiscal_before = {
            "legal_name": profile_before.legal_name, "rfc": profile_before.rfc,
            "tax_regime": profile_before.tax_regime, "tax_zip": profile_before.tax_zip,
            "billing_email": profile_before.billing_email, "color": profile_before.color,
        }
        r = c.patch(f"{pbase}/profile/", data=json.dumps({"rfc": "NO-VALIDO"}), content_type=J)
    else:
        r = c.post(f"{pbase}/profile/", data=json.dumps({"rfc": "NO-VALIDO"}), content_type=J)
        cleanup["profile_created"] = r.status_code == 201
    check("RFC inválido → 400", r.status_code == 400, f"HTTP {r.status_code}")

    payload = {
        "legal_name": "Injoy Comercializadora SA de CV", "rfc": "ico150910abc",
        "tax_regime": "601 — General de Ley PM", "tax_zip": "06600",
        "billing_email": "pagos@injoy.mx", "color": "#db2777",
    }
    if FinanceProfile.objects.filter(project=project).exists():
        r = c.patch(f"{pbase}/profile/", data=json.dumps(payload), content_type=J)
        ok_code = 200
    else:
        r = c.post(f"{pbase}/profile/", data=json.dumps(payload), content_type=J)
        ok_code = 201
        cleanup["profile_created"] = True
    body = r.json()
    check("guardar datos fiscales", r.status_code == ok_code, f"HTTP {r.status_code} {body}")
    check("RFC normalizado a mayúsculas", body.get("rfc") == "ICO150910ABC", str(body.get("rfc")))
    check("color guardado", body.get("color") == "#db2777")
    r = c.patch(f"{pbase}/profile/", data=json.dumps({"tax_zip": "123"}), content_type=J)
    check("CP inválido → 400", r.status_code == 400, f"HTTP {r.status_code}")
    r = c.patch(f"{pbase}/profile/", data=json.dumps({"billing_email": "no-es-correo"}), content_type=J)
    check("correo inválido → 400", r.status_code == 400, f"HTTP {r.status_code}")

    print("\nCSF")
    r = c.post(f"{pbase}/profile/csf/", data=json.dumps({"name": "csf.docx", "type": "application/msword", "size": 1000}), content_type=J)
    check("CSF no-PDF → 400", r.status_code == 400, f"HTTP {r.status_code}")
    r = c.post(f"{pbase}/profile/csf/", data=json.dumps({"name": "csf.pdf", "type": "application/pdf", "size": 20 * 1024 * 1024}), content_type=J)
    check("CSF >10MB → 400", r.status_code == 400, f"HTTP {r.status_code}")
    r = c.post(f"{pbase}/profile/csf/", data=json.dumps({"name": "csf-injoy.pdf", "type": "application/pdf", "size": 123456}), content_type=J)
    body = r.json()
    check("presign de subida", r.status_code == 200 and "upload_data" in body and "asset_id" in body, f"HTTP {r.status_code}")
    asset_id = body.get("asset_id")
    if asset_id:
        cleanup["assets"].append(asset_id)
    r = c.patch(f"{pbase}/profile/csf/", data=json.dumps({"asset_id": asset_id}), content_type=J)
    body = r.json()
    check("confirmar CSF → perfil actualizado", r.status_code == 200 and body.get("csf_name") == "csf-injoy.pdf", f"HTTP {r.status_code} {body.get('csf_name')}")
    r = c.get(f"{pbase}/profile/csf/")
    check("descarga CSF → redirección a storage", r.status_code == 302 and "csf-injoy.pdf" in (r.headers.get("Location") or ""), f"HTTP {r.status_code}")
    # replace: a second upload marks the first as deleted
    r = c.post(f"{pbase}/profile/csf/", data=json.dumps({"name": "csf-v2.pdf", "type": "application/pdf", "size": 999}), content_type=J)
    asset2 = r.json().get("asset_id")
    if asset2:
        cleanup["assets"].append(asset2)
    r = c.patch(f"{pbase}/profile/csf/", data=json.dumps({"asset_id": asset2}), content_type=J)
    # el manager por defecto oculta los soft-deleted: desaparecer = borrado
    _all = getattr(FileAsset, "all_objects", FileAsset.objects)
    old_gone = not FileAsset.objects.filter(pk=asset_id).exists() or _all.get(pk=asset_id).is_deleted
    check("reemplazo marca la anterior como borrada", r.status_code == 200 and old_gone)
    r = c.delete(f"{pbase}/profile/csf/")
    check("quitar CSF", r.status_code == 204, f"HTTP {r.status_code}")
    r = c.get(f"{pbase}/profile/csf/")
    check("sin CSF → 404", r.status_code == 404, f"HTTP {r.status_code}")

    print("\nDASHBOARD: COLORES Y DATOS DE CLIENTE")
    r = c.get(f"{base}/dashboard/")
    clients = r.json().get("clients", [])
    me = next((x for x in clients if x["project_id"] == str(project.id)), None)
    check("cliente presente en dashboard", me is not None)
    check("cliente lleva color", me and me.get("color") == "#db2777", str(me.get("color") if me else None))
    check("cliente lleva RFC y razón social", me and me.get("rfc") == "ICO150910ABC" and me.get("legal_name", "").startswith("Injoy"))
    check("todos los clientes tienen color asignado", all(x.get("color") for x in clients), str([x.get("color") for x in clients]))

    print("\nFILTRO POR FECHAS")
    old_day = today - timedelta(days=400)
    p_old = Payment.objects.create(
        project=project, workspace=ws, amount="1111.00", currency="MXN",
        paid_at=old_day, method="transfer", created_by=admin,
    )
    cleanup["payments"].append(p_old.id)
    p_new = Payment.objects.create(
        project=project, workspace=ws, amount="2222.00", currency="MXN",
        paid_at=today, method="transfer", created_by=admin,
    )
    cleanup["payments"].append(p_new.id)
    d_from = (today - timedelta(days=15)).isoformat()
    r_all = c.get(f"{base}/dashboard/?date_from={old_day.isoformat()}&date_to={today.isoformat()}")
    r_rng = c.get(f"{base}/dashboard/?date_from={d_from}&date_to={today.isoformat()}")
    rev_all = r_all.json()["totals"]["MXN"]["revenue_ytd"]
    rev_rng = r_rng.json()["totals"]["MXN"]["revenue_ytd"]
    check("rango amplio incluye el pago viejo", rev_all >= rev_rng + 1111.0 - 0.01, f"{rev_all} vs {rev_rng}")
    me_rng = next((x for x in r_rng.json()["clients"] if x["project_id"] == str(project.id)), None)
    me_all = next((x for x in r_all.json()["clients"] if x["project_id"] == str(project.id)), None)
    check("revenue por cliente respeta el rango", me_all["revenue"]["MXN"] >= me_rng["revenue"]["MXN"] + 1111.0 - 0.01)
    months_rng = [m["month"] for m in r_rng.json()["monthly_revenue"]]
    check("meses del gráfico ceñidos al rango", len(months_rng) <= 2 and months_rng[-1] == f"{today.year:04d}-{today.month:02d}", str(months_rng))
    # invalid dates are ignored, not an error
    r = c.get(f"{base}/dashboard/?date_from=chatarra")
    check("fecha inválida se ignora", r.status_code == 200, f"HTTP {r.status_code}")
    # pnl range
    r = c.get(f"{base}/pnl/?date_from={old_day.isoformat()}&date_to={today.isoformat()}")
    months = r.json()["months"]
    check("pnl cubre el rango pedido", r.status_code == 200 and 13 <= len(months) <= 15, str(len(months)))
    # expenses range
    e = ExpenseEntry.objects.create(workspace=ws, month="2024-01", category="other", concept="viejo", amount="10.00", currency="MXN", created_by=admin)
    cleanup["expenses"].append(e.id)
    r = c.get(f"{base}/expenses/?date_from={today.replace(day=1).isoformat()}")
    check("gastos filtrados excluyen meses viejos", r.status_code == 200 and all(x["month"] >= f"{today.year:04d}-{today.month:02d}" for x in r.json()))

    print("\nANÁLISIS GUARDADOS")
    # BaseModel.save() auto-asigna created_by desde el usuario del request;
    # fuera de un request hay que pasarlo explícito con created_by_id
    row = FinanceAnalysis(workspace=ws, content="Diagnóstico de prueba.")
    row.save(created_by_id=str(admin.id))
    cleanup["analyses"].append(row.id)
    r = c.get(f"{base}/analyses/")
    body = r.json()
    check("listar análisis", r.status_code == 200 and any(a["id"] == str(row.id) for a in body), f"HTTP {r.status_code}")
    mine = next((a for a in body if a["id"] == str(row.id)), {})
    check("análisis lleva autor y fecha", bool(mine.get("created_by_display_name")) and bool(mine.get("created_at")))
    r = c.delete(f"{base}/analyses/{row.id}/")
    check("eliminar análisis", r.status_code == 204, f"HTTP {r.status_code}")
    check("eliminado de verdad", not FinanceAnalysis.objects.filter(pk=row.id).exists())
    cleanup["analyses"].remove(row.id)

    print("\nPARSE: VALIDACIONES SIN IA")
    r = c.post(f"{base}/import/parse/", data=json.dumps({"content": ""}), content_type=J)
    check("contenido vacío → 400", r.status_code == 400, f"HTTP {r.status_code}")

finally:
    print("\nLIMPIEZA")
    Payment.objects.filter(pk__in=cleanup["payments"]).delete()
    ExpenseEntry.objects.filter(pk__in=cleanup["expenses"]).delete()
    FinanceAnalysis.objects.filter(pk__in=cleanup["analyses"]).delete()
    getattr(FileAsset, "all_objects", FileAsset.objects).filter(pk__in=cleanup["assets"]).delete()
    profile = FinanceProfile.objects.filter(project=project).first()
    if profile:
        if cleanup["profile_created"]:
            profile.delete(soft=False)
        elif fiscal_before is not None:
            for k, v in fiscal_before.items():
                setattr(profile, k, v)
            profile.csf_asset = None
            profile.save()
    print("  hecho")

total, passed = len(results), sum(results)
print(f"\n{'✅' if passed == total else '❌'} {passed}/{total}")
raise SystemExit(0 if passed == total else 1)
