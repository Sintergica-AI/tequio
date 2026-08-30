#!/bin/bash
# Sincroniza apps/admin (god-mode) con el VPS, reconstruye SOLO la imagen admin
# y recrea el contenedor. Espejo de sync-web.sh; existe porque aquel sólo mira
# apps/web, así que un cambio en el panel de administración no llegaba nunca a
# producción y quedaba como código muerto en local.
set -euo pipefail

. "$(cd "$(dirname "$0")" && pwd)/_env.sh"
VPS="$VPS_HOST"
PORT="$VPS_PORT"
KEY="$VPS_KEY"
SRC="$(cd "$(dirname "$0")/../plane-src" && pwd)"
TAG="${1:-v1.4.2-ai}"
# REMOTE_SRC viene de _env.sh

run() { ssh -i "$KEY" -p "$PORT" -o BatchMode=yes "$VPS" "$@"; }

cd "$SRC"
# `add -N` expande los directorios nuevos que git colapsa a "?? dir/".
git add -A -N -- 'apps/admin' >/dev/null 2>&1 || true

TO_COPY=()
TO_DELETE=()
while IFS= read -r line; do
  [ -n "$line" ] || continue
  st="${line:0:2}"
  path="${line:3}"
  path="${path%\"}"; path="${path#\"}"
  if [[ "$st" == *D* ]]; then
    TO_DELETE+=("$path")
  else
    TO_COPY+=("$path")
  fi
done < <(git status --porcelain -- 'apps/admin')

echo "=== ${#TO_COPY[@]} archivos a copiar, ${#TO_DELETE[@]} a borrar ==="

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

# El compose apunta a un tag literal: construir con otro deja la imagen sin usar
# y el despliegue parece correcto sin serlo (le pasó a backend-rebuild.sh).
COMPOSE_DIR=/opt/plane/plane-app
if ! run "grep -q 'plane-admin-custom:$TAG' $COMPOSE_DIR/docker-compose.yaml"; then
  echo "FATAL: docker-compose.yaml no referencia plane-admin-custom:$TAG. Tags que usa:"
  run "grep -o 'plane-admin-custom:[A-Za-z0-9._-]*' $COMPOSE_DIR/docker-compose.yaml | sort -u"
  exit 1
fi

echo "=== Reconstruyendo imagen admin (bloqueante, ~5-10 min) ==="
run "cd $REMOTE_SRC && docker build -f apps/admin/Dockerfile.admin -t plane-admin-custom:$TAG . 2>&1 | tail -8"

echo "=== Recreando contenedor admin ==="
run "cd $COMPOSE_DIR && docker compose -f docker-compose.yaml --env-file=plane.env up -d --no-deps --force-recreate admin"

sleep 15
run "docker ps --format '{{.Label \"com.docker.compose.service\"}}  {{.Image}}  {{.Status}}' | grep '^admin '"
