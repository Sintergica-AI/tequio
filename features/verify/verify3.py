"""Prueba funcional de las funciones nuevas del gestor de archivos:
enlaces externos, etiquetas y relación con módulos. No deja datos.
"""

import json
import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "plane.settings.production")
django.setup()

from django.test import Client  # noqa: E402
from plane.db.models import (  # noqa: E402
    FileAsset,
    Module,
    Project,
    ProjectMember,
    Workspace,
    WorkspaceMember,
)

OK, FAIL = "\033[92mOK\033[0m", "\033[91mFALLO\033[0m"
results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(f"  {OK if cond else FAIL}  {name}" + (f" — {detail}" if detail else ""))


ws = Workspace.objects.first()
user = (
    WorkspaceMember.objects.filter(workspace=ws, role=20, is_active=True).select_related("member").first().member
)
pm = ProjectMember.objects.filter(member=user, is_active=True, role=20).select_related("project").first()
c = Client()
c.force_login(user)
base = f"/api/workspaces/{ws.slug}"
pbase = f"{base}/projects/{pm.project_id}"
J = "application/json"

created = []

try:
    # ------------------------------------------------------------ ENLACES
    print("ENLACES EXTERNOS (Google Drive)")
    gdrive = "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWxYz/view?usp=sharing"
    r = c.post(
        f"{base}/drive/",
        data=json.dumps({"name": "Presupuesto 2026", "kind": "link", "url": gdrive}),
        content_type=J,
    )
    check("crear enlace", r.status_code == 201, f"HTTP {r.status_code}")
    if r.status_code == 201:
        link = r.json()
        created.append(link["id"])
        check("kind = link", link.get("kind") == "link", link.get("kind"))
        check("url conservada", link.get("url") == gdrive)
        check("listo sin subida (is_uploaded)", link.get("is_uploaded") is True)
        check("tamaño 0", link.get("size") == 0)
        r2 = c.get(f"{base}/drive/")
        check("aparece en el listado", any(f["id"] == link["id"] for f in r2.json()))
        r3 = c.get(f"{base}/drive/{link['id']}/")
        check(
            "descarga devuelve la URL en vez de redirigir (sin open redirect)",
            r3.status_code == 200 and r3.json().get("url") == gdrive,
            f"HTTP {r3.status_code}",
        )

    print("\n  Validación de URLs peligrosas")
    for bad, label in [
        ("javascript:alert(1)", "javascript:"),
        ("data:text/html,<script>alert(1)</script>", "data:"),
        ("file:///etc/passwd", "file://"),
        ("no-es-una-url", "texto suelto"),
        ("", "vacía"),
    ]:
        r = c.post(
            f"{base}/drive/",
            data=json.dumps({"name": "malo", "kind": "link", "url": bad}),
            content_type=J,
        )
        check(f"rechaza {label}", r.status_code == 400, f"HTTP {r.status_code}")

    # ------------------------------------------------------------ ETIQUETAS
    print("\nETIQUETAS")
    r = c.post(
        f"{base}/drive/",
        data=json.dumps(
            {
                "name": "Manual",
                "kind": "link",
                "url": "https://docs.google.com/document/d/abc123/edit",
                "tags": ["  Legal  ", "legal", "Contratos", ""],
            }
        ),
        content_type=J,
    )
    check("crear con etiquetas", r.status_code == 201, f"HTTP {r.status_code}")
    if r.status_code == 201:
        item = r.json()
        created.append(item["id"])
        check(
            "recorta, deduplica (sin distinguir mayúsculas) y descarta vacías",
            item["tags"] == ["Legal", "Contratos"],
            str(item["tags"]),
        )
        r = c.patch(
            f"{base}/drive/{item['id']}/",
            data=json.dumps({"tags": ["Finanzas"]}),
            content_type=J,
        )
        check("actualizar etiquetas", r.status_code == 200 and r.json()["tags"] == ["Finanzas"])
        r = c.patch(
            f"{base}/drive/{item['id']}/",
            data=json.dumps({"tags": [f"tag{i}" for i in range(40)]}),
            content_type=J,
        )
        check("limita a 20 etiquetas", r.status_code == 200 and len(r.json()["tags"]) == 20)
        r = c.patch(
            f"{base}/drive/{item['id']}/",
            data=json.dumps({"tags": ["x" * 200]}),
            content_type=J,
        )
        check("recorta etiquetas largas a 50", r.status_code == 200 and len(r.json()["tags"][0]) == 50)
        r = c.patch(f"{base}/drive/{item['id']}/", data=json.dumps({"tags": "no-lista"}), content_type=J)
        check("rechaza etiquetas que no son lista", r.status_code == 400, f"HTTP {r.status_code}")

    # ------------------------------------------------------------ MÓDULOS
    print("\nMÓDULOS")
    module = Module.objects.filter(project_id=pm.project_id).first()
    temp_module = None
    if module is None:
        module = temp_module = Module.objects.create(
            name="Módulo de prueba", project_id=pm.project_id, workspace=ws, created_by=user
        )
    r = c.post(
        f"{pbase}/drive/",
        data=json.dumps(
            {
                "name": "Plano",
                "kind": "link",
                "url": "https://drive.google.com/file/d/xyz/view",
                "module_id": str(module.id),
                "tags": ["Obra"],
            }
        ),
        content_type=J,
    )
    check(f"relacionar con el módulo '{module.name}'", r.status_code == 201, f"HTTP {r.status_code}")
    if r.status_code == 201:
        item = r.json()
        created.append(item["id"])
        check("module_id guardado", item.get("module_id") == str(module.id))
        check("etiqueta guardada junto al módulo", item.get("tags") == ["Obra"])
        r = c.patch(f"{pbase}/drive/{item['id']}/", data=json.dumps({"module_id": None}), content_type=J)
        check("quitar el módulo", r.status_code == 200 and r.json().get("module_id") is None)

    # módulo de OTRO proyecto debe rechazarse
    other = (
        Module.objects.exclude(project_id=pm.project_id).first()
        or Module.objects.filter(project_id=pm.project_id).first()
    )
    foreign = Module.objects.exclude(project_id=pm.project_id).first()
    if foreign:
        r = c.post(
            f"{pbase}/drive/",
            data=json.dumps(
                {"name": "x", "kind": "link", "url": "https://a.com", "module_id": str(foreign.id)}
            ),
            content_type=J,
        )
        check("rechaza un módulo de otro proyecto", r.status_code == 400, f"HTTP {r.status_code}")
    else:
        print("  (no hay módulos de otro proyecto para probar el aislamiento)")

    r = c.post(
        f"{base}/drive/",
        data=json.dumps({"name": "x", "kind": "link", "url": "https://a.com", "module_id": str(module.id)}),
        content_type=J,
    )
    check("rechaza módulo a nivel organización", r.status_code == 400, f"HTTP {r.status_code}")

    r = c.post(
        f"{pbase}/drive/",
        data=json.dumps({"name": "x", "kind": "link", "url": "https://a.com", "module_id": "no-uuid"}),
        content_type=J,
    )
    check("rechaza module_id inválido", r.status_code == 400, f"HTTP {r.status_code}")

    # --------------------------------------------------- SUBIDA NORMAL INTACTA
    print("\nREGRESIÓN: la subida de archivos sigue funcionando")
    r = c.post(
        f"{base}/drive/",
        data=json.dumps({"name": "informe.pdf", "type": "application/pdf", "size": 4096, "tags": ["Reportes"]}),
        content_type=J,
    )
    check("solicitar subida", r.status_code == 200, f"HTTP {r.status_code}")
    if r.status_code == 200:
        aid = r.json()["asset_id"]
        created.append(aid)
        r = c.patch(f"{base}/drive/{aid}/", data=json.dumps({}), content_type=J)
        check("confirmar subida", r.status_code == 200, f"HTTP {r.status_code}")
        if r.status_code == 200:
            check("kind = file por defecto", r.json().get("kind") == "file")
            check("etiquetas conservadas al subir", r.json().get("tags") == ["Reportes"])
        r = c.get(f"{base}/drive/{aid}/?disposition=inline")
        check("previsualización redirige a MinIO", r.status_code == 302, f"HTTP {r.status_code}")
        loc = r.headers.get("Location", "")
        check("la URL de previsualización es inline", "inline" in loc.lower(), loc[:60] + "...")
        r = c.get(f"{base}/drive/{aid}/")
        check("descarga sigue siendo attachment", r.status_code == 302 and "attachment" in r.headers.get("Location", "").lower())

    # SVG no debe servirse inline (riesgo de XSS)
    r = c.post(
        f"{base}/drive/",
        data=json.dumps({"name": "logo.svg", "type": "image/svg+xml", "size": 512}),
        content_type=J,
    )
    if r.status_code == 200:
        sid = r.json()["asset_id"]
        created.append(sid)
        c.patch(f"{base}/drive/{sid}/", data=json.dumps({}), content_type=J)
        r = c.get(f"{base}/drive/{sid}/?disposition=inline")
        check(
            "SVG forzado a descarga aunque se pida inline (anti-XSS)",
            r.status_code == 302 and "attachment" in r.headers.get("Location", "").lower(),
        )
finally:
    for aid in created:
        FileAsset.objects.filter(pk=aid).delete()
    try:
        if temp_module:
            temp_module.delete()
    except NameError:
        pass
    print("\n(datos de prueba eliminados)")

print("=" * 52)
print(f"RESULTADO: {sum(results)}/{len(results)} comprobaciones correctas")
print("=" * 52)
