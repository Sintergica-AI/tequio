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

# Keepalives: sin ellos una conexion muerta no falla, se QUEDA COLGADA para
# siempre — pasó el 31 Ago, 48 minutos parado en un solo scp mientras el proceso
# seguía vivo, que es peor que un error porque nadie lo detecta. Con esto un
# enlace muerto se convierte en fallo en ~45s y el reintento puede empezar.
# (Ese día hubo TRES cortes contra este VPS; si se repite, el arreglo de fondo
# es pasar el transporte a rsync, que además deja el destino consistente.)
#
# Y multiplexado (ControlMaster): el bucle abría DOS conexiones SSH nuevas por
# fichero — un ssh para el mkdir y un scp para copiarlo —, o sea del orden de
# mil handshakes seguidos en una copia completa. Los cuatro cortes del 31 Ago
# ocurrieron todos a mitad de esa ráfaga, con el VPS sano (carga 0.07, 0% de
# pérdida de paquetes, ssh suelto funcionando al instante). No se confirmó la
# causa —no hay baneos de fail2ban ni descartes de sshd en el journal—, así que
# esto NO es un arreglo de una causa conocida: es quitar de en medio la ráfaga,
# que era la única anomalía del patrón. Con el master reutilizado son ~2
# handshakes en total en vez de ~1070, y además va mucho más rápido.
CTL="/tmp/.sync-web-ctl-$$"
SSH_KEEPALIVE=(
  -o ControlMaster=auto -o "ControlPath=$CTL" -o ControlPersist=600
  -o ServerAliveInterval=15 -o ServerAliveCountMax=3 -o ConnectTimeout=15
)
# Cerrar el master al salir: si queda vivo, un cambio de red posterior deja un
# socket que apunta a una conexión muerta y el siguiente sync lo reutiliza.
cleanup_ctl() { ssh -i "$KEY" -p "$PORT" -o "ControlPath=$CTL" -O exit "$VPS" 2>/dev/null || true; rm -f "$CTL"; }
trap cleanup_ctl EXIT

run() { ssh -i "$KEY" -p "$PORT" -o BatchMode=yes "${SSH_KEEPALIVE[@]}" "$VPS" "$@"; }

cd "$SRC"
# git status colapsa directorios enteramente nuevos a "?? dir/", lo que rompería
# la copia archivo-por-archivo. `add -N` (intent-to-add) los expande a archivos
# individuales sin preparar contenido.
git add -A -N -- 'apps/web' 'packages/propel' 'packages/i18n' 'packages/constants' 'packages/editor' 'packages/types' 'packages/utils' >/dev/null 2>&1 || true
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
done < <(git status --porcelain -- 'apps/web' 'packages/propel' 'packages/i18n' 'packages/constants' 'packages/editor' 'packages/types' 'packages/utils' 'pnpm-lock.yaml')
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
  scp -q -i "$KEY" -P "$PORT" "${SSH_KEEPALIVE[@]}" "$SRC/$f" "$VPS:$REMOTE_SRC/$f"
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
