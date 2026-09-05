#!/bin/bash
# Genera el tarball del CÓDIGO FUENTE CORRESPONDIENTE (AGPL-3.0 §13) de una
# versión de Tequio y lo deja en el directorio de salida.
#
# Se arma con LAS MISMAS ENTRADAS con las que CI construye las imágenes: el
# árbol de upstream ya parcheado (de ahí salen web, space, admin y live) y este
# repositorio (de ahí sale el backend). Por eso corresponde por construcción,
# en vez de por buena voluntad de quien despliega — que es como se perdía antes,
# cuando regenerarlo era un paso suelto que se olvidaba.
#
# LISTA BLANCA, NO EXCLUSIONES. Una lista negra se rompe en silencio en cuanto
# aparece un directorio nuevo; la blanca falla cerrada. No la conviertas.
set -euo pipefail

UPSTREAM="${1:?Uso: source-tarball.sh <árbol-upstream-parcheado> <versión> <dir-salida>}"
VERSION="${2:?falta la versión}"
OUT_DIR="${3:?falta el directorio de salida}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

NAME="tequio-source-$VERSION"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/$NAME" "$OUT_DIR"

echo "=== 1/4 Copiando el monorepo parcheado ==="
# node_modules, .git y salidas de compilación no son fuente y multiplican el peso.
rsync -a \
  --exclude 'node_modules/' --exclude '.git/' --exclude '.turbo/' \
  --exclude 'dist/' --exclude 'build/' --exclude '.react-router/' --exclude '*.log' \
  "$UPSTREAM/" "$STAGE/$NAME/plane-src/"

echo "=== 2/4 Copiando las capas propias (lista blanca) ==="
for item in patch features build deploy release.env README.md NOTICE; do
  [ -e "$REPO_ROOT/$item" ] || { echo "FATAL: falta $item en el repo"; exit 1; }
  rsync -a --exclude '__pycache__/' --exclude '*.pyc' \
    "$REPO_ROOT/$item" "$STAGE/$NAME/tequio/"
done

cat > "$STAGE/$NAME/REBUILD.md" <<EOF
# Reconstruir Tequio $VERSION desde este paquete

Este es el código fuente correspondiente de la versión $VERSION de Tequio, una
versión modificada de [Plane](https://github.com/makeplane/plane) Community
Edition distribuida bajo AGPL-3.0. Ver \`plane-src/LICENSE.txt\` y
\`tequio/NOTICE\`.

    plane-src/   monorepo de Plane en $(cat "$REPO_ROOT/release.env" | sed -n 's/^UPSTREAM_REF=//p') con el frontend de Tequio ya aplicado
    tequio/      las capas propias: patch/ y features/ (backend), build/ (recetas), deploy/ (kit de instalación)

Imágenes, y de dónde sale cada una:

    tequio-backend  docker build -f tequio/build/backend/Dockerfile tequio/
    tequio-web      docker build -f plane-src/apps/web/Dockerfile.web   plane-src/
    tequio-space    docker build -f plane-src/apps/space/Dockerfile.space plane-src/
    tequio-admin    docker build -f plane-src/apps/admin/Dockerfile.admin plane-src/
    tequio-live     docker build -f plane-src/apps/live/Dockerfile.live  plane-src/
    tequio-proxy    docker build -f tequio/build/proxy/Dockerfile tequio/

El build de web hornea cuatro valores (\`VITE_SOURCE_CODE_URL\`,
\`VITE_SUPPORT_EMAIL\`, \`VITE_TERMS_URL\`, \`VITE_PRIVACY_URL\`); los valores
usados están en \`tequio/release.env\`.

Para instalar el resultado, \`tequio/deploy/README.md\`.
EOF

echo "=== 3/4 Comprobando que no se cuela nada que no deba ==="
# Falla cerrada: si aparece un secreto, no se publica nada.
#
# Las dos mitades del paquete NO tienen el mismo riesgo, y tratarlas igual
# produjo falsos positivos que empujan a relajar la comprobación entera:
#   - plane-src/ es un clon limpio de upstream. Lo que hay ahí ya está publicado
#     en makeplane/plane (su .npmrc y sus deployments/*/variables.env son
#     plantillas versionadas), así que marcarlo por el NOMBRE no mide nada.
#   - tequio/ sale de una copia de trabajo, y ahí sí puede colarse un deploy.env
#     con el host y la ruta de la llave del VPS, o un plane.env con secretos.
# Por nombre solo se revisa la segunda; por CONTENIDO se revisan las dos.
BAD="$(find "$STAGE/$NAME/tequio" \
        \( -name '*.env' ! -name '*.example' \) -o -name 'id_rsa*' \
        -o -name '*.pem' -o -name '*.key' \
        | grep -v '/release.env$' || true)"
[ -z "$BAD" ] || { echo "FATAL: ficheros sensibles en el paquete:"; echo "$BAD"; exit 1; }
# El patrón se arma partido a propósito: escrito entero, este mismo script se
# empaqueta dentro de tequio/build/ y la búsqueda se encuentra a sí misma. Es un
# falso positivo que aborta cada release, y el arreglo tentador —quitar la
# comprobación— es justo el equivocado.
KEY_PATTERN="-----BEGIN .*PRIVA""TE KEY-----"
if grep -rlqE -- "$KEY_PATTERN" "$STAGE/$NAME" 2>/dev/null; then
  echo "FATAL: hay una clave privada dentro del paquete:"
  grep -rlE -- "$KEY_PATTERN" "$STAGE/$NAME" | head
  exit 1
fi

# Fondo, no forma: que el paquete contenga de verdad las dos mitades. Un tar que
# pesa lo esperado pero sin los módulos propios ofrece un fuente que no
# corresponde, y eso es peor que no ofrecer nada: afirma un cumplimiento falso.
for must in \
  "$NAME/tequio/features/backend/chat/models.py" \
  "$NAME/tequio/features/backend/finance/models.py" \
  "$NAME/tequio/features/backend/assistant/models.py" \
  "$NAME/tequio/patch/patch_ce.py" \
  "$NAME/plane-src/apps/web/core/components/drive" \
  "$NAME/plane-src/LICENSE.txt" ; do
  [ -e "$STAGE/$must" ] || { echo "FATAL: falta en el paquete: $must"; exit 1; }
done
grep -rqs "Tequio" "$STAGE/$NAME/plane-src/packages/i18n/src/locales/es/" \
  || { echo "FATAL: el árbol empaquetado no lleva el frontend de Tequio"; exit 1; }

echo "=== 4/4 Empaquetando ==="
tar -czf "$OUT_DIR/$NAME.tar.gz" -C "$STAGE" "$NAME"
SIZE="$(du -h "$OUT_DIR/$NAME.tar.gz" | cut -f1)"
# Un tarball de pocos KB significa que el rsync copió poco: se ha visto.
BYTES="$(wc -c < "$OUT_DIR/$NAME.tar.gz")"
[ "$BYTES" -gt 5000000 ] || { echo "FATAL: el tarball pesa $BYTES bytes, demasiado poco"; exit 1; }
echo "  $OUT_DIR/$NAME.tar.gz ($SIZE)"
