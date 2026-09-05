#!/bin/bash
# Tequio · instalador para el VPS de un cliente.
#
#   docker run --rm ghcr.io/sintergica-ai/tequio-release:stable cat /kit/install.sh > install.sh
#   sudo bash install.sh --domain tequio.cliente.com --email admin@cliente.com
#
# Deja la instancia en marcha, con actualizaciones automáticas nocturnas y con
# la oferta de código fuente (AGPL §13) publicada en /source/.
#
# No instala Docker: si falta, lo dice y para. Un instalador que descarga y
# ejecuta un script de terceros a espaldas de quien administra el servidor es
# justo lo que no se debe normalizar.
set -euo pipefail

DOMAIN=""; EMAIL=""; CHANNEL="stable"; TEQUIO_HOME="/opt/tequio"
REGISTRY="ghcr.io"; NAMESPACE="sintergica-ai"; ASSUME_YES=0
while [ $# -gt 0 ]; do
  case "$1" in
    --domain)    DOMAIN="$2"; shift 2 ;;
    --email)     EMAIL="$2"; shift 2 ;;
    --channel)   CHANNEL="$2"; shift 2 ;;
    --home)      TEQUIO_HOME="$2"; shift 2 ;;
    --registry)  REGISTRY="$2"; shift 2 ;;
    --namespace) NAMESPACE="$2"; shift 2 ;;
    --yes|-y)    ASSUME_YES=1; shift ;;
    -h|--help)
      sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Opción desconocida: $1"; exit 2 ;;
  esac
done

die() { echo "FATAL: $*" >&2; exit 1; }
say() { echo "==> $*"; }

# --- Requisitos ---------------------------------------------------------------
[ "$(id -u)" -eq 0 ] || die "hay que ejecutarlo como root (sudo)."
command -v docker >/dev/null || die "falta Docker. Instálalo con las instrucciones oficiales
       de tu distribución (https://docs.docker.com/engine/install/) y vuelve a lanzar esto."
docker compose version >/dev/null 2>&1 || die "falta el plugin 'docker compose' (v2)."
command -v openssl >/dev/null || die "falta openssl (paquete openssl)."
command -v curl >/dev/null || die "falta curl."
systemctl --version >/dev/null 2>&1 || die "este instalador espera systemd."

[ -n "$DOMAIN" ] || die "falta --domain (el dominio por el que se accederá a Tequio)."
[ -n "$EMAIL" ] || die "falta --email (aviso de caducidad de certificados)."

if [ -e "$TEQUIO_HOME/tequio.env" ]; then
  die "ya hay una instalación en $TEQUIO_HOME. Para actualizarla: tequio update.
       Para reinstalar desde cero, mueve ese directorio a un lado ANTES (contiene
       los secretos; los datos viven en volúmenes de Docker y no se borran solos)."
fi

# El certificado se pide en el primer arranque: si el DNS no apunta aquí todavía,
# Let's Encrypt falla y Caddy entra en reintentos con espera creciente.
say "comprobando que $DOMAIN apunta a este servidor"
RESOLVED="$(getent ahostsv4 "$DOMAIN" 2>/dev/null | awk '{print $1; exit}' || true)"
MYIP="$(curl -fsS -m 10 https://api.ipify.org 2>/dev/null || true)"
if [ -z "$RESOLVED" ]; then
  echo "    AVISO: $DOMAIN no resuelve. Crea el registro A antes de que Caddy"
  echo "           pida el certificado, o la instancia servirá solo por HTTP."
elif [ -n "$MYIP" ] && [ "$RESOLVED" != "$MYIP" ]; then
  echo "    AVISO: $DOMAIN resuelve a $RESOLVED y este servidor se ve como $MYIP."
else
  echo "    OK: $DOMAIN -> $RESOLVED"
fi

for port in 80 443; do
  if ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]$port$"; then
    die "el puerto $port ya está ocupado. Tequio necesita 80 y 443 (o cámbialos
       con LISTEN_HTTP_PORT/LISTEN_HTTPS_PORT en tequio.env y pon otro proxy delante)."
  fi
done

if [ "$ASSUME_YES" -ne 1 ]; then
  echo
  echo "  Instalar Tequio en $TEQUIO_HOME"
  echo "    dominio : $DOMAIN"
  echo "    canal   : $CHANNEL"
  echo "    imágenes: $REGISTRY/$NAMESPACE/tequio-*"
  echo
  read -r -p "¿Continuar? [s/N] " ans
  case "$ans" in s|S|si|Si|SI|y|Y) ;; *) echo "Cancelado."; exit 1 ;; esac
fi

# --- El kit ------------------------------------------------------------------
# Si este script se ejecuta desde una copia del repo, el kit está al lado. Si se
# sacó de la imagen de release con `cat`, hay que extraerlo.
HERE="$(cd "$(dirname "$0")" && pwd)"
RELEASE_IMAGE="$REGISTRY/$NAMESPACE/tequio-release:$CHANNEL"
if [ -f "$HERE/docker-compose.yaml" ] && [ -x "$HERE/bin/tequio-update" ]; then
  KIT="$HERE"
  say "usando el kit local de $KIT"
else
  say "descargando el kit de $RELEASE_IMAGE"
  docker pull -q "$RELEASE_IMAGE" >/dev/null || die "no pude descargar $RELEASE_IMAGE"
  KIT="$(mktemp -d)"
  CID="$(docker create "$RELEASE_IMAGE")"
  docker cp "$CID:/kit/." "$KIT/" >/dev/null
  docker rm -f "$CID" >/dev/null
fi
[ -f "$KIT/tequio.env.example" ] || die "el kit no trae tequio.env.example"

install -d -m 755 "$TEQUIO_HOME" "$TEQUIO_HOME/bin" "$TEQUIO_HOME/state" \
                  "$TEQUIO_HOME/backups" "$TEQUIO_HOME/kit" "$TEQUIO_HOME/source/public"
install -d -m 755 /var/log/tequio

# --- Configuración -------------------------------------------------------------
say "generando secretos y escribiendo tequio.env"
ENVF="$TEQUIO_HOME/tequio.env"
install -m 600 "$KIT/tequio.env.example" "$ENVF"

set_key() {
  local key="$1" val="$2"
  grep -qE "^${key}=" "$ENVF" || die "la plantilla no tiene la clave $key"
  # El valor va por variable de entorno para que awk no lo interprete.
  VAL="$val" KEY="$key" awk '
    BEGIN { k = ENVIRON["KEY"]; v = ENVIRON["VAL"] }
    index($0, k "=") == 1 { print k "=" v; next }
    { print }
  ' "$ENVF" > "$ENVF.tmp" && mv "$ENVF.tmp" "$ENVF"
  chmod 600 "$ENVF"
}

# Hexadecimal a propósito: una contraseña con caracteres especiales rompe las
# URLs de conexión (DATABASE_URL, AMQP_URL) de formas difíciles de diagnosticar.
set_key SECRET_KEY              "$(openssl rand -hex 32)"
set_key LIVE_SERVER_SECRET_KEY  "$(openssl rand -hex 32)"
set_key POSTGRES_PASSWORD       "$(openssl rand -hex 24)"
set_key RABBITMQ_PASSWORD       "$(openssl rand -hex 24)"
set_key AWS_ACCESS_KEY_ID       "$(openssl rand -hex 10)"
set_key AWS_SECRET_ACCESS_KEY   "$(openssl rand -hex 24)"

set_key APP_DOMAIN            "$DOMAIN"
set_key SITE_ADDRESS          "$DOMAIN"
set_key WEB_URL               "https://$DOMAIN"
set_key CORS_ALLOWED_ORIGINS  "https://$DOMAIN"
set_key CERT_EMAIL            "$EMAIL"
set_key TEQUIO_CHANNEL        "$CHANNEL"
set_key TEQUIO_REGISTRY       "$REGISTRY"
set_key TEQUIO_NAMESPACE      "$NAMESPACE"

# Comprobación de fondo: que no quede vacía ninguna clave que el compose exige.
# Es la misma lista que usa el actualizador, sacada del propio compose.
install -m 644 "$KIT/docker-compose.yaml" "$TEQUIO_HOME/docker-compose.yaml"
# shellcheck disable=SC1090
set -a; . "$ENVF"; set +a
MISSING=""
for k in $(grep -oE '\$\{[A-Z_][A-Z0-9_]*:\?' "$TEQUIO_HOME/docker-compose.yaml" | sed 's/^\${//; s/:?$//' | sort -u); do
  if [ "$k" = "TEQUIO_VERSION" ]; then continue; fi
  if [ -z "${!k:-}" ]; then MISSING="$MISSING $k"; fi
done
[ -z "$MISSING" ] || die "quedaron claves sin valor:$MISSING"

# --- Instalación del kit y del temporizador ------------------------------------
install -m 755 "$KIT/bin/"* "$TEQUIO_HOME/bin/"
install -m 644 "$KIT/tequio.env.example" "$TEQUIO_HOME/tequio.env.example"
ln -sf "$TEQUIO_HOME/bin/tequio" /usr/local/bin/tequio
install -m 644 "$KIT/systemd/tequio-update.service" /etc/systemd/system/
install -m 644 "$KIT/systemd/tequio-update.timer"   /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now tequio-update.timer

# --- Primer despliegue ---------------------------------------------------------
# Lo hace el actualizador: descarga, migra, levanta, publica el fuente y
# comprueba salud. Un camino distinto para la primera vez sería un camino que
# solo se ejercita una vez y por eso se pudre sin que nadie lo note.
say "desplegando (descarga de imágenes, migraciones y arranque)"
TEQUIO_HOME="$TEQUIO_HOME" "$TEQUIO_HOME/bin/tequio-update" || {
  echo
  echo "El primer despliegue falló. El registro está en /var/log/tequio/."
  echo "Cuando lo arregles, reintenta con:  tequio update --force"
  exit 1
}

cat <<FIN

  Tequio instalado.

    Abre        https://$DOMAIN
    Panel       https://$DOMAIN/god-mode/   (crea ahí el usuario administrador)
    Fuente      https://$DOMAIN/source/     (AGPL-3.0 §13)

    Estado           tequio status
    Actualizar ya    tequio update
    Diagnóstico      tequio doctor

  Las actualizaciones se aplican solas cada madrugada (canal $CHANNEL).
  Configura el correo saliente en /god-mode/email/ antes de invitar a nadie:
  sin correo no salen las invitaciones ni los enlaces mágicos.

FIN
