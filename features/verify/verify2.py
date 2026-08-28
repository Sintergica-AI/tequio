"""Compara el guardado de contenido entre una página de PROYECTO (código de
fábrica de Plane CE) y una página de WIKI (código nuevo), con la misma carga
útil. Sirve para saber si el HTTP 500 es un bug introducido o de CE.
"""

import base64
import json
import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "plane.settings.production")
django.setup()

from django.test import Client  # noqa: E402
from plane.db.models import Page, Project, ProjectMember, Workspace, WorkspaceMember  # noqa: E402

OK, FAIL = "\033[92mOK\033[0m", "\033[91mFALLO\033[0m"

ws = Workspace.objects.first()
user = (
    WorkspaceMember.objects.filter(workspace=ws, role=20, is_active=True)
    .select_related("member")
    .first()
    .member
)
pm = ProjectMember.objects.filter(member=user, is_active=True, role=20).select_related("project").first()
c = Client()
c.force_login(user)
base = f"/api/workspaces/{ws.slug}"
pbase = f"{base}/projects/{pm.project_id}"

# Carga útil realista: binario Yjs codificado en base64 (lo que manda el editor)
real_binary = base64.b64encode(bytes([0, 1, 2, 3, 4, 5])).decode()
payloads = {
    "cadena vacía (la de mi prueba anterior)": "",
    "base64 real (lo que manda el editor)": real_binary,
}

created = []
try:
    # --- página de proyecto (código de fábrica) ---
    r = c.post(
        f"{pbase}/pages/",
        data=json.dumps({"name": "cmp proyecto", "access": 0}),
        content_type="application/json",
    )
    proj_page = r.json()["id"]
    created.append(("proj", proj_page))

    # --- página de wiki (código nuevo) ---
    r = c.post(
        f"{base}/pages/",
        data=json.dumps({"name": "cmp wiki", "access": 0}),
        content_type="application/json",
    )
    wiki_page = r.json()["id"]
    created.append(("wiki", wiki_page))

    for label, binary in payloads.items():
        print(f"\nCarga útil: {label}")
        body = json.dumps(
            {
                "description_html": "<p>contenido de prueba</p>",
                "description_json": {"type": "doc"},
                "description_binary": binary,
            }
        )
        rp = c.patch(f"{pbase}/pages/{proj_page}/description/", data=body, content_type="application/json")
        rw = c.patch(f"{base}/pages/{wiki_page}/description/", data=body, content_type="application/json")
        same = rp.status_code == rw.status_code
        print(f"  página de PROYECTO (Plane de fábrica): HTTP {rp.status_code}")
        print(f"  página de WIKI     (código nuevo)    : HTTP {rw.status_code}")
        print(f"  {OK if same else FAIL}  comportamiento idéntico: {same}")
        if rw.status_code == 200:
            pg = Page.objects.get(pk=wiki_page)
            saved = pg.description_html == "<p>contenido de prueba</p>"
            print(f"  {OK if saved else FAIL}  contenido persistido en la wiki: {saved}")
finally:
    for kind, pid in created:
        Page.objects.filter(pk=pid).delete()
    print("\n(páginas de prueba eliminadas)")
