"""Genera la versión Tequio de emails/notifications/issue-updates.html a partir
de la plantilla de Plane v1.4.2.

Se hace por script y no a mano porque el original es un archivo denso de 242
líneas: cada sustitución lleva su aserción, así que si upstream cambia una
cadena el generador falla en vez de dejar el texto sin traducir.
"""

import os
import re
import sys

def _ancestro_con(sub, que):
    """Sube desde este archivo hasta encontrar un directorio que contenga `sub`.

    El árbol de trabajo y el repositorio colocan estos scripts en sitios
    distintos (`sintergica-features/` suelto vs `features/scripts/` y
    `features/verify/` dentro del repo tequio), así que una ruta relativa
    fija funciona en uno y falla en el otro. Se busca y se AFIRMA el hallazgo:
    mejor un error que diga qué falta que trabajar sobre el árbol equivocado.
    """
    d = os.path.dirname(os.path.abspath(__file__))
    while True:
        if os.path.exists(os.path.join(d, sub)):
            return d
        padre = os.path.dirname(d)
        if padre == d:
            raise SystemExit(f"FATAL: no encuentro {que} ({sub}) desde {__file__}")
        d = padre


FEATURES = _ancestro_con("backend/emails", "el paquete de features")
ARBOL = _ancestro_con("plane-src/apps/api", "el árbol de fuentes de Plane")
SRC = os.path.join(ARBOL, "plane-src/apps/api/templates/emails/notifications/issue-updates.html")
DST = os.path.join(FEATURES, "backend/emails/notifications/issue-updates.html")

t = open(SRC, encoding="utf-8").read()
fallos = []


def sub(old, new, count=None, label=""):
    """Sustituye exigiendo un número exacto de apariciones."""
    global t
    n = t.count(old)
    if count is None:
        count = 1
    if n != count:
        fallos.append(f"{label or old[:50]!r}: esperaba {count} apariciones, hay {n}")
        return
    t = t.replace(old, new)


def sub_re(pattern, new, count, label):
    global t
    n = len(re.findall(pattern, t))
    if n != count:
        fallos.append(f"{label}: esperaba {count} coincidencias, hay {n}")
        return
    t = re.sub(pattern, new, t)


# --- 1. Identidad: logotipo -------------------------------------------------
sub(
    '<div style="margin-left: 30px; margin-bottom: 20px; margin-top: 20px" > '
    '<img src="https://media.docs.plane.so/logo/new-logo-white.png" width="150" border="0" /> </div>',
    '<div style="margin-left: 30px; margin-bottom: 20px; margin-top: 20px" > '
    '<span style="font-size: 22px; font-weight: 600; letter-spacing: 0.5px; color: #000c19;">Tequio</span> </div>',
    label="logotipo de cabecera",
)

# --- 2. Redes de Plane Software, Inc. --------------------------------------
sub_re(
    r'<div style="margin-top: 60px; float: right">.*?</div>',
    "",
    1,
    "bloque de redes sociales",
)

# --- 3. Iconos alojados en el bucket de Plane -------------------------------
# La flecha entre valor viejo y nuevo sí carga significado: se sustituye por
# una flecha de texto. Los demás iconos son decorativos y se eliminan.
sub_re(
    r'<img src="https://plane-marketing\.s3\.ap-south-1\.amazonaws\.com/plane-assets/emails/forward-arrow\.png"[^>]*/>',
    '<span style="font-size: 0.8rem; color: #60646c;">&#8594;</span>',
    2,
    "flecha entre valores",
)
sub_re(
    r'<img src="https://plane-marketing\.s3[^>]*/>\s*',
    "",
    8,
    "iconos decorativos del bucket de Plane",
)
# Los dos iconos de estado no empiezan por https://: el src entero es un
# condicional de plantilla que elige entre cinco imágenes del mismo bucket.
sub_re(
    r'<img src="\{% if update\.changes\.state[^>]*/>\s*',
    "",
    2,
    "iconos de estado del bucket de Plane",
)

# --- 3b. Código de plantilla comentado ---------------------------------------
# Upstream dejó comentado un párrafo alternativo ("There are N new updates and
# M new comments on the issue") que usa variables que el contexto ya no define.
# No se ve, pero se renderiza en cada correo y su texto en inglés sobreviviría
# a cualquier traducción: se elimina.
sub_re(
    r"<!-- \{% if actors_involved == 1 %\}.*?-->",
    "",
    1,
    "párrafo alternativo comentado",
)

# --- 4. Textos ---------------------------------------------------------------
sub("<title>Updates on {{entity_type}}</title>", "<title>Novedades del {{entity_type}}</title>", label="title")
sub("{{ issue.issue_identifier }} updates ", "Novedades de {{ issue.issue_identifier }} ", label="encabezado")
sub("</span>and others. </p>", "</span> y otras personas. </p>", label="y otras personas")
sub(
    "The {{entity_type}} title has been updated to",
    "El título del {{entity_type}} cambió a",
    label="cambio de título",
)
sub('color: #121a26"> Updates </p>', 'color: #121a26"> Cambios </p>', label="bloque Cambios")
sub("padding-bottom: 20px;\"> Comments </p>", "padding-bottom: 20px;\"> Comentarios </p>", label="bloque Comentarios")
sub("> Due Date: </p>", "> Fecha límite: </p>", label="Due Date")
sub("> State: </p>", "> Estado: </p>", label="State")
sub("> Links: </p>", "> Enlaces: </p>", label="Links")
sub("> Priority: </p>", "> Prioridad: </p>", label="Priority")
sub("> 2 Links were removed </p>", "> Se quitaron 2 enlaces </p>", label="enlaces quitados")
sub("> Duplicate: </span>", "> Duplicado de: </span>", label="Duplicate")
sub("> Assignee: </span>", "> Responsable: </span>", label="Assignee")
sub("> Labels: </span>", "> Etiquetas: </span>", label="Labels")
sub("> Blocking: </span>", "> Bloquea a: </span>", label="Blocking")
sub_re(r"\}\} more </span>", "}} más </span>", 8, "+N more")

# Pie
sub(
    "This email was sent to",
    "Este mensaje se envió a",
    label="pie: destinatario",
)
sub(
    "If you'd rather not receive this kind of email,",
    "Si prefieres no recibir correos así,",
    label="pie: preferencia",
)
sub(
    ">you can unsubscribe to the {{entity_type}}</a >",
    ">puedes dejar de seguir este {{entity_type}}</a >",
    label="pie: dejar de seguir",
)
sub(
    "</a > or <a href=\"{{ user_preference }}\"",
    "</a > o <a href=\"{{ user_preference }}\"",
    label="pie: conjuncion",
)
sub(
    ">manage your email preferences</a >",
    ">ajustar tus preferencias de correo</a >",
    label="pie: preferencias",
)

# Botón que lleva al elemento de trabajo
sub("> View {{entity_type}} </div>", "> Ver el {{entity_type}} </div>", label="botón Ver")

# Nada de inglés suelto en el TEXTO VISIBLE. Se mira solo lo que queda tras
# quitar comentarios, etiquetas de plantilla y marcado: los nombres de variable
# (issue_url, issue.name) siguen en inglés a propósito, son código.
visible = re.sub(r"<!--.*?-->", "", t, flags=re.DOTALL)
visible = re.sub(r"\{[{%].*?[%}]\}", " ", visible, flags=re.DOTALL)
visible = re.sub(r"<[^>]+>", " ", visible)
sobrantes = re.findall(
    r"\b(View|issue|updates|comments|and others|has been|This email|unsubscribe)\b", visible
)
if sobrantes:
    fallos.append(f"queda texto visible en inglés: {sorted(set(sobrantes))}")

# --- 5. Aserciones finales ---------------------------------------------------
if fallos:
    print("FALLOS de generación:")
    for f in fallos:
        print("  -", f)
    sys.exit(1)

for prohibido in ("plane.so", "makeplane", "planepowers", "plane-marketing", "Plane"):
    if prohibido in t:
        ctx = t[max(0, t.find(prohibido) - 80) : t.find(prohibido) + 80]
        print(f"FATAL: queda {prohibido!r} en la salida:\n  ...{ctx}...")
        sys.exit(1)

cabecera = (
    "{% comment %}\n"
    "Copyright (c) 2023-present Plane Software, Inc. and contributors\n"
    "Modificaciones (c) 2026 Sintergica AI - identidad Tequio\n"
    "SPDX-License-Identifier: AGPL-3.0-only\n"
    "\n"
    "Resumen de novedades de un elemento de trabajo. Derivada de la plantilla de\n"
    "Plane CE v1.4.2; a diferencia del resto de correos NO usa _tequio_base.html\n"
    "porque su maqueta es propia (bloques de cambios por propiedad).\n"
    "\n"
    "Cambios respecto al original: logotipo de Plane -> marca Tequio; se retiran\n"
    "los enlaces a github.com/makeplane, LinkedIn y x.com de Plane Software, Inc.;\n"
    "se dejan de cargar los 12 iconos alojados en el bucket de marketing de Plane\n"
    "(la flecha entre valor viejo y nuevo pasa a ser un caracter); y los textos\n"
    "van en español. Los nombres de estado y prioridad se muestran tal como los\n"
    "guarda la base de datos, igual que en el original.\n"
    "{% endcomment %}"
)
t = cabecera + t

open(DST, "w", encoding="utf-8").write(t)
print(f"OK escrito {DST} ({len(t)} bytes)")
