#!/bin/bash
# Deja en $1 el árbol de Plane upstream CON el frontend de Tequio aplicado.
# De ahí salen las imágenes web, space, admin y live, y de ahí sale también el
# tarball de código fuente correspondiente (AGPL §13): el mismo árbol para los
# dos, que es justo lo que exige "Corresponding Source".
#
# Todo lo que puede fallar aquí falla EN SILENCIO si no se comprueba:
#  - un tag movido en upstream cambia los binarios sin cambiar nada nuestro,
#  - `git apply` de un parche vacío sale con 0 y deja el árbol de fábrica,
#  - un parche sin --binary aplica los textos y se deja los logotipos.
# Por eso cada paso afirma lo que espera encontrar.
set -euo pipefail

DEST="${1:?Uso: prepare-upstream.sh <directorio-destino>}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
. "$REPO_ROOT/release.env"

PATCH="$REPO_ROOT/features/web-live.patch"
[ -s "$PATCH" ] || { echo "FATAL: no existe o está vacío $PATCH"; exit 1; }

echo "=== 1/4 Clonando $UPSTREAM_REPO @ $UPSTREAM_REF ==="
rm -rf "$DEST"
git clone --quiet --depth 1 --branch "$UPSTREAM_REF" "$UPSTREAM_REPO" "$DEST"
cd "$DEST"

GOT="$(git rev-parse HEAD)"
if [ -n "${UPSTREAM_COMMIT:-}" ] && [ "$GOT" != "$UPSTREAM_COMMIT" ]; then
  echo "FATAL: $UPSTREAM_REF apunta a $GOT y se esperaba $UPSTREAM_COMMIT."
  echo "       Upstream movió el tag. Revisa qué cambió ANTES de publicar nada:"
  echo "       los anclajes de los patchers y el parche del frontend se hicieron"
  echo "       contra el commit esperado."
  exit 1
fi
echo "  commit $GOT (verificado)"

echo "=== 2/4 Aplicando features/web-live.patch ==="
# --binary porque el parche lleva los assets del rebranding (favicons, vídeo del
# login) codificados; sin esa bandera git los rechaza y el rebranding sale a
# medias: textos nuevos con logotipos de Plane.
git apply --binary --whitespace=nowarn "$PATCH"

echo "=== 3/4 Verificando el resultado ==="
# `git apply` de un parche vacío o truncado sale con 0. Se cuenta lo que quedó
# realmente modificado en el árbol, no lo que decía el fichero.
CHANGED=$(git status --porcelain | wc -l | tr -d ' ')
MIN_CHANGED=400
if [ "$CHANGED" -lt "$MIN_CHANGED" ]; then
  echo "FATAL: el parche dejó $CHANGED archivos modificados, se esperaban ≥ $MIN_CHANGED."
  exit 1
fi
echo "  $CHANGED archivos modificados"

# Fondo, no forma: que existan los módulos que dan de comer, no solo que el
# contador cuadre. Cada uno de estos ya se quedó fuera del despliegue alguna vez.
REQUIRED_PATHS=(
  apps/web/core/components/drive
  apps/web/core/components/chat
  apps/web/core/components/assistant
  apps/web/core/components/pages/workspace
  apps/live/src/services/page/workspace-page.service.ts
  apps/live/src/services/chat-channel.service.ts
  apps/live/src/controllers/chat.controller.ts
)
FAIL=0
for p in "${REQUIRED_PATHS[@]}"; do
  [ -e "$p" ] || { echo "FALTA: $p"; FAIL=1; }
done
[ "$FAIL" -eq 0 ] || { echo "FATAL: el parche no trajo módulos que sí deberían estar."; exit 1; }

# El rebranding vive repartido; si el parche viaja sin packages/propel o sin
# apps/space, la interfaz sigue diciendo Plane en sitios visibles.
grep -rqs "Tequio" packages/i18n/src/locales/es/ \
  || { echo "FATAL: los locales no traen las cadenas de Tequio"; exit 1; }
grep -rqs "Tequio" packages/propel/src apps/space \
  || { echo "FATAL: el rebranding no llegó a propel/space (logotipos y sitio público)"; exit 1; }

echo "=== 4/4 Árbol listo en $DEST ==="
