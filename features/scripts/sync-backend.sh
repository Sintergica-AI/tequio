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
scp -q -i "$KEY" -P "$PORT" "$DIR/backend-rebuild.sh" "$VPS:/opt/sintergica-features/"

echo "=== Reconstruyendo y desplegando ==="
ssh -i "$KEY" -p "$PORT" "$VPS" "bash /opt/sintergica-features/backend-rebuild.sh '$TAG'"
