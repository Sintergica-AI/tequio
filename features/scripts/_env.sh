# Carga la configuración de despliegue. Se incluye desde los demás scripts.
# Prioridad: variables de entorno ya definidas > deploy.env > error.
_here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$_here/deploy.env" ]; then
  # shellcheck disable=SC1090
  . "$_here/deploy.env"
fi
: "${VPS_HOST:?Falta VPS_HOST. Copia deploy.env.example a deploy.env y complétalo.}"
: "${VPS_PORT:=22}"
: "${VPS_KEY:=$HOME/.ssh/id_rsa}"
: "${REMOTE_SRC:=/opt/plane-src}"
# Raíz del paquete (features/) y árbol de fuentes de Plane en local.
PKG="$(cd "$_here/.." && pwd)"
: "${PLANE_SRC:=$PKG/../../plane-src}"
