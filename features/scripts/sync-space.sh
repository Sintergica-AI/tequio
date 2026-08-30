#!/bin/bash
# Sincroniza apps/space (sitio público de tableros) con el VPS, reconstruye SOLO
# la imagen space y recrea el contenedor. Espejo de sync-admin.sh.
#
# POR QUÉ EXISTE: sync-web.sh mira apps/web (+ packages) y sync-admin.sh mira
# apps/admin. Nadie miraba apps/space, y además el servicio corría la imagen DE
# FÁBRICA `makeplane/plane-space`, así que ningún cambio local podía llegar a
# producción — el sitio público seguía mostrando la marca Plane mientras el
# resto de la instancia ya era Tequio.
#
# REQUISITO PREVIO (una sola vez): el servicio `space` del docker-compose.yaml
# tiene que apuntar a la imagen custom. De fábrica trae la forma con VARIABLE
#     image: makeplane/plane-space:${APP_RELEASE:-v1.4.2}
# y hay que dejarla como tag literal
#     image: plane-space-custom:v1.4.2-tequio
# La comprobación de más abajo falla en seco si no se hizo: construir una imagen
# que el compose no referencia deja un despliegue que parece correcto sin serlo.
set -euo pipefail

. "$(cd "$(dirname "$0")" && pwd)/_env.sh"
VPS="$VPS_HOST"
PORT="$VPS_PORT"
KEY="$VPS_KEY"
SRC="$(cd "$(dirname "$0")/../plane-src" && pwd)"
TAG="${1:-v1.4.2-tequio}"
# REMOTE_SRC viene de _env.sh

run() { ssh -i "$KEY" -p "$PORT" -o BatchMode=yes "$VPS" "$@"; }

cd "$SRC"
# `add -N` expande los directorios nuevos que git colapsa a "?? dir/".
# packages/* va incluido porque la marca (logotipos) vive en packages/propel y
# los textos en packages/i18n y packages/constants: sin ellos, space se
# reconstruye con la identidad vieja. Es el mismo fallo que tuvo sync-web.sh.
PATHS=('apps/space' 'packages/propel' 'packages/i18n' 'packages/constants' 'packages/editor')
git add -A -N -- "${PATHS[@]}" >/dev/null 2>&1 || true

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
done < <(git status --porcelain -- "${PATHS[@]}" 'pnpm-lock.yaml')

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

COMPOSE_DIR=/opt/plane/plane-app
if ! run "grep -q 'plane-space-custom:$TAG' $COMPOSE_DIR/docker-compose.yaml"; then
  echo "FATAL: docker-compose.yaml no referencia plane-space-custom:$TAG."
  echo "Referencias actuales del servicio space:"
  run "grep -n -A2 '^  space:' $COMPOSE_DIR/docker-compose.yaml | grep image:"
  echo
  echo "Si es la primera vez, haz el cambio único descrito en la cabecera de este"
  echo "script (con copia de seguridad del compose antes)."
  exit 1
fi

echo "=== Reconstruyendo imagen space (bloqueante, ~5-10 min) ==="
run "cd $REMOTE_SRC && docker build -f apps/space/Dockerfile.space -t plane-space-custom:$TAG . 2>&1 | tail -8"

echo "=== Recreando contenedor space ==="
run "cd $COMPOSE_DIR && docker compose -f docker-compose.yaml --env-file=plane.env up -d --no-deps --force-recreate space"

sleep 15
run "docker ps --format '{{.Label \"com.docker.compose.service\"}}  {{.Image}}  {{.Status}}' | grep '^space '"
