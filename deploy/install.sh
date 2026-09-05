#!/bin/bash
# Tequio · instalador para el VPS de un cliente.
#
# Servidor dedicado (Tequio toma 80/443 y emite su propio certificado):
#   sudo bash install.sh --domain tequio.cliente.com --email admin@cliente.com
#
# Servidor que ya sirve otras aplicaciones (Tequio escucha en un puerto alto y
# el proxy que ya existe le reenvía el dominio; el TLS lo sigue haciendo él):
#   sudo bash install.sh --domain tequio.cliente.com --behind-proxy
#
# Opciones:
#   --domain DOM        dominio público de la instancia (obligatorio)
#   --email  MAIL       aviso de caducidad del certificado (obligatorio salvo --behind-proxy)
#   --behind-proxy      no toca 80/443 ni emite certificado
#   --http-port  N      puerto publicado en el host (por defecto 80, u 8080 con --behind-proxy)
#   --https-port N      idem (443, u 8443)
#   --channel CANAL     stable (por defecto) o edge
#   --home DIR          dónde vive la instalación (por defecto /opt/tequio)
#   --yes               no preguntar
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
BEHIND_PROXY=0; HTTP_PORT=""; HTTPS_PORT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --domain)       DOMAIN="$2"; shift 2 ;;
    --email)        EMAIL="$2"; shift 2 ;;
    --channel)      CHANNEL="$2"; shift 2 ;;
    --home)         TEQUIO_HOME="$2"; shift 2 ;;
    --registry)     REGISTRY="$2"; shift 2 ;;
    --namespace)    NAMESPACE="$2"; shift 2 ;;
    --behind-proxy) BEHIND_PROXY=1; shift ;;
    --http-port)    HTTP_PORT="$2"; shift 2 ;;
    --https-port)   HTTPS_PORT="$2"; shift 2 ;;
    --yes|-y)       ASSUME_YES=1; shift ;;
    -h|--help)
      # Hasta la primera línea que ya no es comentario: contar líneas a mano se
      # queda corto en cuanto la cabecera crece, y entonces --help escupe código.
      awk 'NR>1 && /^#/ { sub(/^# ?/, ""); print; next } NR>1 { exit }' "$0"; exit 0 ;;
    *) echo "Opción desconocida: $1"; exit 2 ;;
  esac
done

# Modo "detrás de un proxy que ya existe": el Caddy de Tequio sirve HTTP plano en
# un puerto alto y NO pide certificado; de la parte pública y del TLS se sigue
# encargando el nginx/Caddy/Traefik que ya atiende el dominio del servidor.
# Es el modo correcto en un servidor compartido: sin él habría que quitarle los
# puertos 80/443 a lo que ya está sirviendo ahí.
if [ "$BEHIND_PROXY" -eq 1 ]; then
  : "${HTTP_PORT:=8080}"
  : "${HTTPS_PORT:=8443}"
else
  : "${HTTP_PORT:=80}"
  : "${HTTPS_PORT:=443}"
fi

die() { echo "FATAL: $*" >&2; exit 1; }
say() { echo "==> $*"; }

# --- Requisitos ---------------------------------------------------------------
[ "$(id -u)" -eq 0 ] || die "hay que ejecutarlo como root (sudo)."

# Las imágenes se construyen en los runners de GitHub, que son x86_64, y no se
# publican para ARM. Sin esta comprobación el fallo llega mucho más tarde y en
# forma de "no matching manifest for linux/arm64", que no menciona ni Tequio ni
# la arquitectura como causa.
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64|amd64) ;;
  *) die "este servidor es $ARCH y las imágenes de Tequio solo se publican para
       x86_64. Hace falta un servidor x86_64 (o construir las imágenes para esta
       arquitectura desde el repositorio)." ;;
esac
command -v docker >/dev/null || die "falta Docker. Instálalo con las instrucciones oficiales
       de tu distribución (https://docs.docker.com/engine/install/) y vuelve a lanzar esto."
docker compose version >/dev/null 2>&1 || die "falta el plugin 'docker compose' (v2)."
command -v openssl >/dev/null || die "falta openssl (paquete openssl)."
command -v curl >/dev/null || die "falta curl."
systemctl --version >/dev/null 2>&1 || die "este instalador espera systemd."

[ -n "$DOMAIN" ] || die "falta --domain (el dominio por el que se accederá a Tequio)."
if [ "$BEHIND_PROXY" -eq 0 ] && [ -z "$EMAIL" ]; then
  die "falta --email (aviso de caducidad de certificados). Con --behind-proxy no hace falta:
       el certificado lo emite el proxy que ya tienes."
fi

if [ -e "$TEQUIO_HOME/tequio.env" ]; then
  die "ya hay una instalación en $TEQUIO_HOME. Para actualizarla: tequio update.
       Para reinstalar desde cero, mueve ese directorio a un lado ANTES (contiene
       los secretos; los datos viven en volúmenes de Docker y no se borran solos)."
fi

# El certificado se pide en el primer arranque: si el DNS no apunta aquí todavía,
# Let's Encrypt falla y Caddy entra en reintentos con espera creciente. Detrás de
# un proxy ajeno esto no aplica —el certificado no lo pide Tequio—, pero el aviso
# sigue siendo útil para saber si el dominio llegará alguna vez.
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

# Se comprueban LOS PUERTOS QUE SE VAN A PUBLICAR, no 80/443 fijos.
#
# Y se exige una herramienta para mirarlos: `ss -ltn` sobre un sistema sin `ss`
# no falla, devuelve nada, y el instalador daría los puertos por libres justo en
# el caso en que más importa —un servidor con otras cosas sirviendo—. Un falso
# negativo aquí se paga con el proxy en bucle de reinicios y el sitio del
# vecino caído.
if command -v ss >/dev/null; then
  LISTENERS="$(ss -ltnH 2>/dev/null | awk '{print $4}')"
elif command -v netstat >/dev/null; then
  LISTENERS="$(netstat -ltn 2>/dev/null | awk '{print $4}')"
else
  die "no encuentro ni 'ss' ni 'netstat' para comprobar qué puertos están ocupados.
       Instala uno (paquete iproute2) y repite: instalar a ciegas en un servidor
       compartido puede tumbar lo que ya está sirviendo."
fi
for port in "$HTTP_PORT" "$HTTPS_PORT"; do
  if printf '%s\n' "$LISTENERS" | grep -qE "[:.]${port}\$"; then
    if [ "$BEHIND_PROXY" -eq 1 ]; then
      die "el puerto $port ya está ocupado. Elige otro con --http-port/--https-port."
    fi
    die "el puerto $port ya está ocupado, seguramente por otro servidor web.
       En un servidor que ya sirve otras aplicaciones, instala con:
         --behind-proxy --http-port 8080 --https-port 8443
       y deja que el proxy que ya tienes reenvíe $DOMAIN a 127.0.0.1:8080.
       Así Tequio no le quita los puertos a nada."
  fi
done

if [ "$ASSUME_YES" -ne 1 ]; then
  echo
  echo "  Instalar Tequio en $TEQUIO_HOME"
  echo "    dominio : $DOMAIN"
  echo "    canal   : $CHANNEL"
  echo "    imágenes: $REGISTRY/$NAMESPACE/tequio-*"
  if [ "$BEHIND_PROXY" -eq 1 ]; then
    echo "    modo    : detrás de tu proxy — escucha en 127.0.0.1:$HTTP_PORT, sin tocar 80/443"
  else
    echo "    modo    : autónomo — toma los puertos $HTTP_PORT y $HTTPS_PORT y emite su certificado"
  fi
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
set_key WEB_URL               "https://$DOMAIN"
set_key CORS_ALLOWED_ORIGINS  "https://$DOMAIN"
set_key LISTEN_HTTP_PORT      "$HTTP_PORT"
set_key LISTEN_HTTPS_PORT     "$HTTPS_PORT"
if [ "$BEHIND_PROXY" -eq 1 ]; then
  # `:80` es el puerto DENTRO del contenedor; el de fuera lo fija
  # LISTEN_HTTP_PORT. Con dos puntos y sin dominio, Caddy sirve HTTP plano y no
  # intenta emitir certificado — lo emite el proxy que ya está delante.
  set_key SITE_ADDRESS        ":80"
  set_key CERT_EMAIL          ""
  # La salud se mide en local: durante la instalación el proxy de fuera todavía
  # no reenvía nada, y medir por el dominio público diría "no arrancó" de algo
  # que arrancó perfectamente.
  set_key TEQUIO_HEALTH_URL   "http://127.0.0.1:$HTTP_PORT"
  set_key LISTEN_BIND_IP      "127.0.0.1"
else
  set_key SITE_ADDRESS        "$DOMAIN"
  set_key CERT_EMAIL          "$EMAIL"
fi
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

if [ "$BEHIND_PROXY" -eq 1 ]; then
  cat <<PROXYFIN

  Tequio está en marcha en http://127.0.0.1:$HTTP_PORT, pero TODAVÍA NO SE LLEGA
  desde fuera: falta que tu proxy reenvíe $DOMAIN aquí.

  Caddy:
    $DOMAIN {
        reverse_proxy 127.0.0.1:$HTTP_PORT
        request_body { max_size 110MB }
    }

  nginx:
    server {
        server_name $DOMAIN;
        client_max_body_size 110m;   # sin esto, el gestor de archivos falla en 1 MB
        location / {
            proxy_pass http://127.0.0.1:$HTTP_PORT;
            proxy_http_version 1.1;
            proxy_set_header Host              \$host;
            proxy_set_header X-Real-IP         \$remote_addr;
            proxy_set_header X-Forwarded-For   \$proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto \$scheme;
            proxy_set_header Upgrade           \$http_upgrade;   # el chat y el
            proxy_set_header Connection        "upgrade";        # editor usan WebSocket
        }
    }

  Los dos ajustes que se olvidan y duelen después: el límite de tamaño del cuerpo
  (o las subidas mueren) y la cabecera Upgrade (o el chat y la edición en vivo
  se quedan reintentando para siempre).

PROXYFIN
fi

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
