#!/bin/bash
# Sincroniza los archivos del frontend con el VPS, reconstruye SOLO la imagen web
# y recrea el contenedor. Usar tras cambios que no tocan backend ni live.
#
# packages/propel entró en la lista el 30 Ago: ahí viven los componentes de
# logotipo, y sin él un rebranding sale a medias (textos nuevos, logos viejos).
#
# Maneja altas, modificaciones Y BAJAS: si un archivo se borró en local hay que
# borrarlo también en el VPS, o quedaría código muerto que aún se compila.
set -euo pipefail

. "$(cd "$(dirname "$0")" && pwd)/_env.sh"
VPS="$VPS_HOST"
PORT="$VPS_PORT"
KEY="$VPS_KEY"
SRC="$(cd "$(dirname "$0")/../plane-src" && pwd)"
TAG="${1:-wiki-drive}"
# REMOTE_SRC viene de _env.sh

run() { ssh -i "$KEY" -p "$PORT" -o BatchMode=yes "$VPS" "$@"; }

cd "$SRC"
# git status colapsa directorios enteramente nuevos a "?? dir/", lo que rompería
# la copia archivo-por-archivo. `add -N` (intent-to-add) los expande a archivos
# individuales sin preparar contenido.
git add -A -N -- 'apps/web' 'packages/propel' 'packages/i18n' 'packages/constants' 'packages/editor' >/dev/null 2>&1 || true
# status porcelain: XY <ruta>. La X/Y es "D" cuando el archivo se borró.
# (bash 3.2 de macOS no tiene mapfile, así que se lee con un while)
TO_COPY=()
TO_DELETE=()
while IFS= read -r line; do
  [ -n "$line" ] || continue
  st="${line:0:2}"
  path="${line:3}"
  path="${path%\"}"; path="${path#\"}"   # git entrecomilla rutas con espacios
  if [[ "$st" == *D* ]]; then
    TO_DELETE+=("$path")
  else
    TO_COPY+=("$path")
  fi
done < <(git status --porcelain -- 'apps/web' 'packages/propel' 'packages/i18n' 'packages/constants' 'packages/editor' 'pnpm-lock.yaml')
# pnpm-lock.yaml es imprescindible: el Dockerfile instala con
# --frozen-lockfile, así que si package.json cambia y el lock no viaja,
# el build falla.

echo "=== ${#TO_COPY[@]} archivos a copiar, ${#TO_DELETE[@]} a borrar ==="

# bash 3.2 + `set -u`: expandir un array vacío es un error, de ahí el ${a[@]+...}
for f in ${TO_DELETE[@]+"${TO_DELETE[@]}"}; do
  run "rm -f '$REMOTE_SRC/$f'"
  echo "  borrado: $f"
done

for f in ${TO_COPY[@]+"${TO_COPY[@]}"}; do
  [ -f "$SRC/$f" ] || { echo "FATAL: $f no existe en local"; exit 1; }
  run "mkdir -p '$REMOTE_SRC/$(dirname "$f")'"
  scp -q -i "$KEY" -P "$PORT" "$SRC/$f" "$VPS:$REMOTE_SRC/$f"
  echo "  copiado: $f"
done

# Poda: los archivos que nunca llegaron a git (untracked y luego borrados) no
# aparecen en `git status`, así que se comparan directamente los directorios que
# esta función posee. Sin esto quedaría código muerto que el build sigue compilando.
OWNED_DIRS="apps/web/public/media apps/web/core/components/drive apps/web/core/components/assistant apps/web/core/components/chat apps/web/core/components/pages/workspace packages/editor/src/core/extensions/code"
for d in $OWNED_DIRS; do
  [ -d "$SRC/$d" ] || continue
  local_files=$(cd "$SRC/$d" && ls -1 2>/dev/null | sort)
  remote_files=$(run "ls -1 '$REMOTE_SRC/$d' 2>/dev/null | sort" || true)
  extra=$(comm -13 <(echo "$local_files") <(echo "$remote_files") || true)
  for f in $extra; do
    run "rm -f '$REMOTE_SRC/$d/$f'"
    echo "  podado (ya no existe en local): $d/$f"
  done
done

echo "=== Reconstruyendo imagen web (bloqueante, ~8-15 min) ==="
# Se ejecuta en primer plano: si falla, este script falla. No usar pgrep para
# esperar — hay watchers antiguos cuya línea de comando contiene "docker build".
# Las VITE_* se hornean en el bundle: no basta con ponerlas en el entorno del
# contenedor, hay que pasarlas como build-arg. Vacias por defecto; se definen en
# deploy.env. Ver source-offer/README.md para el enlace de codigo fuente.
BUILD_ARGS="--build-arg VITE_SOURCE_CODE_URL=${VITE_SOURCE_CODE_URL:-}"
BUILD_ARGS="$BUILD_ARGS --build-arg VITE_SUPPORT_EMAIL=${VITE_SUPPORT_EMAIL:-}"
BUILD_ARGS="$BUILD_ARGS --build-arg VITE_TERMS_URL=${VITE_TERMS_URL:-}"
BUILD_ARGS="$BUILD_ARGS --build-arg VITE_PRIVACY_URL=${VITE_PRIVACY_URL:-}"
# Sin pipe directo: "docker build | tail" devuelve el exit de tail y un build
# roto pasaba en silencio (ocurrio el 30 Ago: lockfile nuevo + package.json
# viejo -> frozen-lockfile fallo y el script recreo la imagen VIEJA como si nada).
run "cd $REMOTE_SRC && docker build $BUILD_ARGS -f apps/web/Dockerfile.web -t plane-web-custom:$TAG . >/tmp/web-build.log 2>&1; EC=\$?; tail -12 /tmp/web-build.log; exit \$EC"

echo "=== Recreando contenedor web ==="
run "cd /opt/plane/plane-app && docker compose -f docker-compose.yaml --env-file=plane.env up -d --no-deps --force-recreate web"

sleep 15
run "docker ps --format '{{.Label \"com.docker.compose.service\"}}  {{.Image}}  {{.Status}}' | grep '^web '"
