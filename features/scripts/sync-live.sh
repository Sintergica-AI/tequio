#!/bin/bash
# Sincroniza apps/live con el VPS, reconstruye la imagen del servidor de
# colaboración y recrea el contenedor. Mismo mecanismo que sync-web.sh
# (git status → copiar/borrar → build en /opt/plane-src), acotado a apps/live.
#
# El chat (canales) usa este servidor como bus de eventos: documentType
# "channel" + endpoint POST /broadcast. Orden de despliegue de la fase 3:
# live PRIMERO (debe aceptar el tipo y el endpoint), luego backend, luego web.
set -euo pipefail

. "$(cd "$(dirname "$0")" && pwd)/_env.sh"
VPS="$VPS_HOST"
PORT="$VPS_PORT"
KEY="$VPS_KEY"
SRC="$(cd "$(dirname "$0")/../plane-src" && pwd)"
TAG="${1:-wiki-drive}"

run() { ssh -i "$KEY" -p "$PORT" -o BatchMode=yes "$VPS" "$@"; }

cd "$SRC"
git add -A -N -- 'apps/live' >/dev/null 2>&1 || true
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
done < <(git status --porcelain -- 'apps/live')

echo "=== ${#TO_COPY[@]} archivos a copiar, ${#TO_DELETE[@]} a borrar (apps/live) ==="
[ "${#TO_COPY[@]}" -gt 0 ] || { echo "FATAL: cero cambios en apps/live — ¿parche sin aplicar?"; exit 1; }

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

# Fondo, no forma: los archivos clave del chat deben existir en el remoto.
for f in apps/live/src/services/chat-channel.service.ts apps/live/src/controllers/chat.controller.ts; do
  run "test -f '$REMOTE_SRC/$f'" || { echo "FATAL: falta $f en el remoto"; exit 1; }
done
run "grep -q '\"channel\"' '$REMOTE_SRC/apps/live/src/types/index.ts'" \
  || { echo "FATAL: el remoto no acepta documentType channel"; exit 1; }

echo "=== Reconstruyendo imagen live (bloqueante, ~10-20 min) ==="
# Sin pipe directo: el exit del build debe llegar a set -e (ver sync-web.sh).
run "cd $REMOTE_SRC && docker build -f apps/live/Dockerfile.live -t plane-live-custom:$TAG . >/tmp/live-build.log 2>&1; EC=\$?; tail -12 /tmp/live-build.log; exit \$EC"

echo "=== Verificando que el compose referencia plane-live-custom:$TAG ==="
run "grep -q 'plane-live-custom:$TAG' /opt/plane/plane-app/docker-compose.yaml" \
  || { echo "FATAL: el compose no usa plane-live-custom:$TAG"; exit 1; }

echo "=== Recreando contenedor live ==="
run "cd /opt/plane/plane-app && docker compose -f docker-compose.yaml --env-file=plane.env up -d --no-deps --force-recreate live"

sleep 15
run "docker ps --format '{{.Label \"com.docker.compose.service\"}}  {{.Image}}  {{.Status}}' | grep '^live '"
