#!/bin/bash
# Sincroniza los archivos del backend con el VPS, reconstruye la imagen del api
# (derivada de la oficial, sin recompilar fuentes) y recrea api + workers.
set -euo pipefail

. "$(cd "$(dirname "$0")" && pwd)/_env.sh"
# Un enlace SSH muerto NO falla: se CUELGA indefinidamente (31 Ago 2026: un
# scp de sync-web.sh estuvo 48 min parado, proceso vivo y log congelado, sin
# error que detectar). Con esto un enlace muerto se vuelve fallo en ~45 s.
# El arreglo de fondo seria rsync sobre SSH, que ademas deja el destino
# consistente tras un corte en vez de mezclado.
#
# Aqui el riesgo NO son las rafagas de conexiones sino la INACTIVIDAD: el
# ultimo ssh lanza backend-rebuild.sh y se queda minutos construyendo la
# imagen sin trafico, que es el caso de libro del cuelgue silencioso.
#
# POR QUE ESTE SCRIPT NO LLEVA ControlMaster y los otros cuatro SI (no es un
# olvido, no lo "unifiques"): sync-web.sh abria ~1070 conexiones seguidas
# (dos por fichero) y los cortes caian siempre a mitad de esa rafaga, asi que
# multiplexar le quita el problema de raiz. Este script hace 9 invocaciones en
# toda su ejecucion: no hay rafaga que eliminar, y ControlMaster solo anadiria
# un socket persistente y un trap de limpieza — dos piezas mas que pueden
# fallar a cambio de nada. Si algun dia esto pasa a copiar arboles de ficheros
# (los emails ya lo son y crecen), la premisa cambia y entonces si toca.
SSH_KEEPALIVE=(-o ServerAliveInterval=15 -o ServerAliveCountMax=3 -o ConnectTimeout=15)
VPS="$VPS_HOST"
PORT="$VPS_PORT"
KEY="$VPS_KEY"
DIR="$(cd "$(dirname "$0")" && pwd)"
TAG="${1:-wiki-drive}"

echo "=== Subiendo archivos del backend ==="
# Los .py del remoto se borran antes de copiar: si aquí se renombra o elimina
# un archivo, dejarlo atrás en el VPS lo mantendría vivo dentro de la imagen.
for app in finance assistant chat; do
  ssh -i "$KEY" -p "$PORT" "${SSH_KEEPALIVE[@]}" "$VPS" \
    "mkdir -p /opt/sintergica-features/backend/$app/migrations && rm -f /opt/sintergica-features/backend/$app/*.py /opt/sintergica-features/backend/$app/migrations/*.py"
done
scp -q -i "$KEY" -P "$PORT" "${SSH_KEEPALIVE[@]}" "$DIR/backend/"*.py "$VPS:/opt/sintergica-features/backend/"
for app in finance assistant chat; do
  scp -q -i "$KEY" -P "$PORT" "${SSH_KEEPALIVE[@]}" "$DIR/backend/$app/"*.py "$VPS:/opt/sintergica-features/backend/$app/"
  scp -q -i "$KEY" -P "$PORT" "${SSH_KEEPALIVE[@]}" "$DIR/backend/$app/migrations/"*.py "$VPS:/opt/sintergica-features/backend/$app/migrations/"
done

# Plantillas de correo (identidad Tequio). Va el arbol COMPLETO en un tar en vez
# de una lista de subdirectorios: el arbol ya tiene seis (auth, exports,
# invitations, notifications, user y la raiz) y una lista escrita a mano aqui se
# queda corta EN SILENCIO en cuanto se anade otro — es el mismo fallo que ya
# mordio en sync-web.sh. Se borra el remoto antes para que una plantilla
# renombrada aqui no sobreviva alla.
EMAILS_LOCAL=$(find "$DIR/backend/emails" -name '*.html' | wc -l | tr -d ' ')
[ "$EMAILS_LOCAL" -gt 0 ] || { echo "FATAL: no hay plantillas de correo en $DIR/backend/emails"; exit 1; }
ssh -i "$KEY" -p "$PORT" "${SSH_KEEPALIVE[@]}" "$VPS" "rm -rf /opt/sintergica-features/backend/emails"
# COPYFILE_DISABLE: el tar de macOS mete ficheros ._ de metadatos que luego
# viajarian dentro de la imagen.
COPYFILE_DISABLE=1 tar -C "$DIR/backend" -cf - emails \
  | ssh -i "$KEY" -p "$PORT" "${SSH_KEEPALIVE[@]}" "$VPS" "mkdir -p /opt/sintergica-features/backend && tar -C /opt/sintergica-features/backend -xf -"
EMAILS_REMOTO=$(ssh -i "$KEY" -p "$PORT" "${SSH_KEEPALIVE[@]}" "$VPS" "find /opt/sintergica-features/backend/emails -name '*.html' | wc -l" | tr -d ' ')
[ "$EMAILS_LOCAL" = "$EMAILS_REMOTO" ] || {
  echo "FATAL: llegaron $EMAILS_REMOTO plantillas de correo y hay $EMAILS_LOCAL aqui."; exit 1; }
echo "  $EMAILS_REMOTO plantillas de correo sincronizadas"
scp -q -i "$KEY" -P "$PORT" "${SSH_KEEPALIVE[@]}" "$DIR/backend-rebuild.sh" "$VPS:/opt/sintergica-features/"

echo "=== Reconstruyendo y desplegando ==="
ssh -i "$KEY" -p "$PORT" "${SSH_KEEPALIVE[@]}" "$VPS" "bash /opt/sintergica-features/backend-rebuild.sh '$TAG'"
