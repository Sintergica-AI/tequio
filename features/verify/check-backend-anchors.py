"""Comprueba EN LOCAL que los anclajes de los dos patchers de backend existen,
encadenándolos en el mismo orden en que corren dentro de la imagen.

POR QUÉ ENCADENADOS: la capa 2 (features/backend/patch_ce_features.py) ancla
sobre ficheros que la capa 1 (patch/patch_ce.py) YA modificó. Comprobar la capa
2 contra el árbol de upstream a secas responde a una pregunta distinta de la que
se le está haciendo, y contesta que sí: pasó el 5 Sep 2026 con el cliente de
OpenAI de external/base.py, cuya línea original ya no existe en la imagen.

Uso:  python3 features/verify/check-backend-anchors.py [ruta-a-plane-src]
Sale con 1 si algún ancla no aparece. No escribe nada en disco.
"""

import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
SRC = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else REPO.parent / "plane-src"
API = SRC / "apps/api"

if not API.exists():
    print(f"FATAL: no encuentro el árbol del api en {API}")
    sys.exit(1)

files = {}
fallos = []


def _load(path):
    if path not in files:
        real = API / path.replace("/code/", "")
        if not real.exists():
            fallos.append(f"{path}: el fichero no existe en el árbol")
            files[path] = ""
        else:
            files[path] = real.read_text()
    return files[path]


def patch(path, old, new, must=True):
    c = _load(path)
    if old not in c:
        if must:
            fallos.append(f"{path}: ancla no encontrada -> {old[:100]!r}")
        return
    if new in c:
        return
    files[path] = c.replace(old, new, 1)


def _run(script, desde=None, hasta=None):
    src = script.read_text()
    i = src.index(desde) if desde else 0
    j = src.index(hasta) if hasta else len(src)
    # Cada patcher define su propio patch(), que escribe en /code. Se le cambia
    # el nombre para que las llamadas usen el de aquí, que solo comprueba.
    if desde is None:
        assert "def patch(" in src, f"{script}: ya no define patch()"
    # Se ejecuta solo el cuerpo de patches, sin la fase de compilación final
    # (esa toca /code de verdad y aquí no hay imagen).
    cuerpo = src[i:j].replace("def patch(", "def _patcher_real(", 1)
    exec(compile(cuerpo, str(script), "exec"), {"patch": patch, "re": __import__("re"), "sys": sys})


_run(REPO / "patch/patch_ce.py", hasta="# 3. Sanity: compile every file")

# La capa 2 se ejecuta en dos tramos: en medio hay un inventario de plantillas
# de correo que LEE /code/templates de verdad, y eso solo existe dentro de la
# imagen. Ese bloque ya se verifica en el build; aquí solo interesan los anclajes.
CAPA2 = REPO / "features/backend/patch_ce_features.py"
_run(CAPA2, hasta="PLANTILLAS = {")
_run(CAPA2, desde="# TELEMETRÍA: fuera", hasta="# Sanity: compile every file")

if fallos:
    print(f"FALLOS ({len(fallos)}):")
    for f in fallos:
        print("  -", f)
    sys.exit(1)
print(f"OK: todos los anclajes de las dos capas existen ({len(files)} ficheros tocados)")
