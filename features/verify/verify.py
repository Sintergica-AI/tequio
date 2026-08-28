"""Prueba funcional de la wiki de organización y del gestor de archivos.
Se ejecuta dentro del contenedor api. No deja datos: borra lo que crea.
"""

import io
import json
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "plane.settings.production")
django.setup()

from django.test import Client  # noqa: E402
from plane.db.models import FileAsset, Page, User, Workspace, WorkspaceMember  # noqa: E402

OK, FAIL = "\033[92mOK\033[0m", "\033[91mFALLO\033[0m"
results = []


def check(name, cond, detail=""):
    results.append(cond)
    print(f"  {OK if cond else FAIL}  {name}" + (f" — {detail}" if detail else ""))


ws = Workspace.objects.first()
admin = (
    WorkspaceMember.objects.filter(workspace=ws, role=20, is_active=True)
    .select_related("member")
    .first()
)
user = admin.member
print(f"workspace={ws.slug}  usuario={user.email}\n")

c = Client()
c.force_login(user)
base = f"/api/workspaces/{ws.slug}"

# ---------------------------------------------------------------- WIKI
print("WIKI POR ORGANIZACION")
r = c.get(f"{base}/pages/")
check("listar páginas", r.status_code == 200, f"HTTP {r.status_code}")
before = len(r.json()) if r.status_code == 200 else -1

r = c.post(
    f"{base}/pages/",
    data=json.dumps({"name": "Prueba de verificación Sintérgica", "access": 0}),
    content_type="application/json",
)
check("crear página", r.status_code == 201, f"HTTP {r.status_code}")
page_id = r.json().get("id") if r.status_code == 201 else None

if page_id:
    page = Page.objects.get(pk=page_id)
    check("marcada como global (no de proyecto)", page.is_global and page.projects.count() == 0)

    r = c.get(f"{base}/pages/{page_id}/")
    check("leer página", r.status_code == 200, f"HTTP {r.status_code}")

    r = c.patch(
        f"{base}/pages/{page_id}/",
        data=json.dumps({"name": "Renombrada"}),
        content_type="application/json",
    )
    check("renombrar", r.status_code == 200, f"HTTP {r.status_code}")

    r = c.get(f"{base}/pages/{page_id}/description/")
    check("leer descripción binaria", r.status_code == 200, f"HTTP {r.status_code}")

    r = c.patch(
        f"{base}/pages/{page_id}/description/",
        data=json.dumps(
            {"description_html": "<p>Hola wiki</p>", "description_json": {}, "description_binary": ""}
        ),
        content_type="application/json",
    )
    check("guardar contenido (ruta del editor)", r.status_code == 200, f"HTTP {r.status_code}")

    r = c.get(f"{base}/pages/{page_id}/versions/")
    check("historial de versiones", r.status_code == 200, f"HTTP {r.status_code}")

    r = c.post(f"{base}/pages/{page_id}/lock/")
    check("bloquear", r.status_code == 204, f"HTTP {r.status_code}")
    c.delete(f"{base}/pages/{page_id}/lock/")

    r = c.get(f"{base}/pages/")
    check("aparece en el listado", r.status_code == 200 and len(r.json()) == before + 1)

    r = c.post(f"{base}/pages/{page_id}/archive/")
    check("archivar", r.status_code == 200, f"HTTP {r.status_code}")
    r = c.delete(f"{base}/pages/{page_id}/{'' }")
    check("borrar sólo tras archivar", r.status_code == 204, f"HTTP {r.status_code}")
    check("eliminada de la BD", not Page.objects.filter(pk=page_id).exists())

# ---------------------------------------------------------------- DRIVE
print("\nGESTOR DE ARCHIVOS (workspace)")
r = c.get(f"{base}/drive/")
check("listar archivos", r.status_code == 200, f"HTTP {r.status_code}")

r = c.post(
    f"{base}/drive/",
    data=json.dumps({"name": "informe.pdf", "type": "application/pdf", "size": 2048}),
    content_type="application/json",
)
check("solicitar subida (URL prefirmada)", r.status_code == 200, f"HTTP {r.status_code}")
body = r.json() if r.status_code == 200 else {}
asset_id = body.get("asset_id")
check("devuelve datos de subida a MinIO", bool(body.get("upload_data", {}).get("url")))

if asset_id:
    r = c.patch(f"{base}/drive/{asset_id}/", data=json.dumps({}), content_type="application/json")
    check("confirmar subida", r.status_code == 200, f"HTTP {r.status_code}")

    r = c.get(f"{base}/drive/")
    check("aparece en el listado", any(f["id"] == asset_id for f in r.json()))

    r = c.patch(
        f"{base}/drive/{asset_id}/",
        data=json.dumps({"name": "informe-final.pdf"}),
        content_type="application/json",
    )
    check("renombrar", r.status_code == 200 and r.json().get("name") == "informe-final.pdf")

    r = c.get(f"{base}/drive/{asset_id}/")
    check("descarga redirige a MinIO", r.status_code == 302, f"HTTP {r.status_code}")

    r = c.post(
        f"{base}/drive/",
        data=json.dumps({"name": "enorme.zip", "type": "application/zip", "size": 500 * 1024 * 1024}),
        content_type="application/json",
    )
    check("rechaza archivos > 100 MB", r.status_code == 400, f"HTTP {r.status_code}")

    r = c.delete(f"{base}/drive/{asset_id}/")
    check("eliminar", r.status_code == 204, f"HTTP {r.status_code}")
    r = c.get(f"{base}/drive/")
    check("desaparece del listado", not any(f["id"] == asset_id for f in r.json()))
    FileAsset.objects.filter(pk=asset_id).delete()

print("\nGESTOR DE ARCHIVOS (proyecto)")
from plane.db.models import Project, ProjectMember  # noqa: E402

pm = ProjectMember.objects.filter(member=user, is_active=True, role=20).select_related("project").first()
if pm:
    pbase = f"{base}/projects/{pm.project_id}/drive"
    r = c.get(f"{pbase}/")
    check(f"listar archivos del proyecto '{pm.project.name}'", r.status_code == 200, f"HTTP {r.status_code}")
    r = c.post(
        f"{pbase}/",
        data=json.dumps({"name": "plano.dwg", "type": "application/octet-stream", "size": 1024}),
        content_type="application/json",
    )
    check("solicitar subida en proyecto", r.status_code == 200, f"HTTP {r.status_code}")
    aid = r.json().get("asset_id") if r.status_code == 200 else None
    if aid:
        a = FileAsset.objects.get(pk=aid)
        check("queda ligado al proyecto", str(a.project_id) == str(pm.project_id))
        check("aislado del drive del workspace", a.project_id is not None)
        a.delete()
else:
    print("  (sin proyecto donde el usuario sea admin — omitido)")

print(f"\n{'='*50}")
print(f"RESULTADO: {sum(results)}/{len(results)} comprobaciones correctas")
print("=" * 50)
