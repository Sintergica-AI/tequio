#!/bin/bash
# Sincroniza los archivos del backend con el VPS, reconstruye la imagen del api
# (derivada de la oficial, sin recompilar fuentes) y recrea api + workers.
set -euo pipefail

. "$(cd "$(dirname "$0")" && pwd)/_env.sh"
VPS="$VPS_HOST"
PORT="$VPS_PORT"
KEY="$VPS_KEY"
TAG="${1:-wiki-drive}"

echo "=== Subiendo archivos del backend ==="
ssh -i "$KEY" -p "$PORT" "$VPS" "mkdir -p /opt/sintergica-features/backend"
scp -q -i "$KEY" -P "$PORT" "$PKG/backend/"*.py "$VPS:/opt/sintergica-features/backend/"
scp -q -i "$KEY" -P "$PORT" "$PKG/scripts/backend-rebuild.sh" "$VPS:/opt/sintergica-features/"

echo "=== Reconstruyendo y desplegando ==="
ssh -i "$KEY" -p "$PORT" "$VPS" "bash /opt/sintergica-features/backend-rebuild.sh '$TAG'"
