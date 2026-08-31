#!/bin/bash
# Sincroniza los archivos del backend con el VPS, reconstruye la imagen del api
# (derivada de la oficial, sin recompilar fuentes) y recrea api + workers.
set -euo pipefail

. "$(cd "$(dirname "$0")" && pwd)/_env.sh"
VPS="$VPS_HOST"
PORT="$VPS_PORT"
KEY="$VPS_KEY"
DIR="$(cd "$(dirname "$0")" && pwd)"
TAG="${1:-wiki-drive}"

echo "=== Subiendo archivos del backend ==="
# Los .py del remoto se borran antes de copiar: si aquí se renombra o elimina
# un archivo, dejarlo atrás en el VPS lo mantendría vivo dentro de la imagen.
for app in finance assistant chat; do
  ssh -i "$KEY" -p "$PORT" "$VPS" \
    "mkdir -p /opt/sintergica-features/backend/$app/migrations && rm -f /opt/sintergica-features/backend/$app/*.py /opt/sintergica-features/backend/$app/migrations/*.py"
done
scp -q -i "$KEY" -P "$PORT" "$DIR/backend/"*.py "$VPS:/opt/sintergica-features/backend/"
for app in finance assistant chat; do
  scp -q -i "$KEY" -P "$PORT" "$DIR/backend/$app/"*.py "$VPS:/opt/sintergica-features/backend/$app/"
  scp -q -i "$KEY" -P "$PORT" "$DIR/backend/$app/migrations/"*.py "$VPS:/opt/sintergica-features/backend/$app/migrations/"
done

# Plantillas de correo (identidad Tequio). Va el arbol COMPLETO en un tar en vez
# de una lista de subdirectorios: el arbol ya tiene seis (auth, exports,
# invitations, notifications, user y la raiz) y una lista escrita a mano aqui se
# queda corta EN SILENCIO en cuanto se anade otro — es el mismo fallo que ya
# mordio en sync-web.sh. Se borra el remoto antes para que una plantilla
# renombrada aqui no sobreviva alla.
EMAILS_LOCAL=$(find "$DIR/backend/emails" -name '*.html' | wc -l | tr -d ' ')
[ "$EMAILS_LOCAL" -gt 0 ] || { echo "FATAL: no hay plantillas de correo en $DIR/backend/emails"; exit 1; }
ssh -i "$KEY" -p "$PORT" "$VPS" "rm -rf /opt/sintergica-features/backend/emails"
# COPYFILE_DISABLE: el tar de macOS mete ficheros ._ de metadatos que luego
# viajarian dentro de la imagen.
COPYFILE_DISABLE=1 tar -C "$DIR/backend" -cf - emails \
  | ssh -i "$KEY" -p "$PORT" "$VPS" "mkdir -p /opt/sintergica-features/backend && tar -C /opt/sintergica-features/backend -xf -"
EMAILS_REMOTO=$(ssh -i "$KEY" -p "$PORT" "$VPS" "find /opt/sintergica-features/backend/emails -name '*.html' | wc -l" | tr -d ' ')
[ "$EMAILS_LOCAL" = "$EMAILS_REMOTO" ] || {
  echo "FATAL: llegaron $EMAILS_REMOTO plantillas de correo y hay $EMAILS_LOCAL aqui."; exit 1; }
echo "  $EMAILS_REMOTO plantillas de correo sincronizadas"
scp -q -i "$KEY" -P "$PORT" "$DIR/backend-rebuild.sh" "$VPS:/opt/sintergica-features/"

echo "=== Reconstruyendo y desplegando ==="
ssh -i "$KEY" -p "$PORT" "$VPS" "bash /opt/sintergica-features/backend-rebuild.sh '$TAG'"
