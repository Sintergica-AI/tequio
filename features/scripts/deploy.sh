#!/bin/bash
# Sintergica: sube el paquete al VPS y ejecuta el despliegue remoto.
# Uso: ./deploy.sh   (desde la carpeta sintergica-features)
set -euo pipefail

. "$(cd "$(dirname "$0")" && pwd)/_env.sh"
VPS="$VPS_HOST"
PORT="$VPS_PORT"
KEY="$VPS_KEY"
DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Subiendo paquete al VPS ==="
ssh -i "$KEY" -p "$PORT" "$VPS" "mkdir -p /opt/sintergica-features/backend"
scp -i "$KEY" -P "$PORT" "$DIR/web-live.patch" "$DIR/remote-deploy.sh" "$VPS:/opt/sintergica-features/"
scp -i "$KEY" -P "$PORT" "$DIR/backend/"*.py "$VPS:/opt/sintergica-features/backend/"

echo "=== Ejecutando despliegue remoto ==="
ssh -i "$KEY" -p "$PORT" "$VPS" "bash /opt/sintergica-features/remote-deploy.sh"
