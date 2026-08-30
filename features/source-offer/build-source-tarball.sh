#!/bin/bash
# Genera el tarball del CÓDIGO FUENTE CORRESPONDIENTE que exige la AGPL-3.0 §13
# y lo deja donde Caddy lo sirve. Se ejecuta EN EL VPS.
#
# Se genera desde el árbol REALMENTE DESPLEGADO (/opt/plane-src y las capas de
# backend), no desde un repositorio aparte: así el fuente ofrecido corresponde
# por construcción a los binarios que la instancia está sirviendo, que es
# justo lo que pide la definición de "Corresponding Source".
#
# LISTA BLANCA, NO EXCLUSIONES. Es deliberado: /opt/sintergica-features contiene
# db-backups/ con datos reales de clientes y ficheros de entorno con credenciales.
# Un tar con --exclude se rompe en cuanto alguien añade un directorio nuevo;
# una lista blanca falla cerrada. No la conviertas en lista negra.
set -euo pipefail

STAGE=/tmp/tequio-source-build
OUT_DIR=/opt/plane-source-offer/public
SRC=/opt/plane-src
STAMP="$(date +%Y%m%d)"
NAME="tequio-source-${STAMP}"

rm -rf "$STAGE"
mkdir -p "$STAGE/$NAME" "$OUT_DIR"

echo "=== 1/5 Copiando el monorepo (sin artefactos de compilación) ==="
# node_modules, .git y salidas de build no son fuente y multiplican el tamaño.
rsync -a \
  --exclude 'node_modules/' \
  --exclude '.git/' \
  --exclude '.turbo/' \
  --exclude 'dist/' \
  --exclude 'build/' \
  --exclude '.react-router/' \
  --exclude '*.log' \
  "$SRC/" "$STAGE/$NAME/plane-src/"

echo "=== 2/5 Copiando las capas de backend (lista blanca) ==="
mkdir -p "$STAGE/$NAME/backend-layers/plane-backend-patch"
cp /opt/plane-backend-patch/*.py /opt/plane-backend-patch/Dockerfile \
   "$STAGE/$NAME/backend-layers/plane-backend-patch/"

mkdir -p "$STAGE/$NAME/backend-layers/sintergica-features"
cp /opt/sintergica-features/*.py /opt/sintergica-features/*.sh \
   "$STAGE/$NAME/backend-layers/sintergica-features/" 2>/dev/null || true
# backend/ son los módulos Django propios (finance, assistant, drive, wiki).
rsync -a --exclude '__pycache__/' \
  /opt/sintergica-features/backend/ \
  "$STAGE/$NAME/backend-layers/sintergica-features/backend/"

echo "=== 3/5 Escribiendo README y licencia ==="
cp "$SRC/LICENSE.txt" "$STAGE/$NAME/LICENSE.txt"
cat > "$STAGE/$NAME/README.md" <<'EOF'
# Código fuente de Tequio

Este paquete es el **código fuente correspondiente** de la instancia de Tequio
desde la que lo has descargado, tal y como exige la sección 13 de la GNU Affero
General Public License v3.

## Qué es Tequio

Tequio es una **versión modificada de Plane**
(https://github.com/makeplane/plane), Copyright (c) 2023-present Plane Software,
Inc. and contributors, licenciada bajo AGPL-3.0-only. Las modificaciones son de
Sintergica AI, 2026.

"Plane" es una marca de Plane Software, Inc. Tequio no está afiliado a Plane
Software, Inc. ni cuenta con su respaldo. Su mención aquí es la atribución de
autoría que la licencia exige.

Punto de partida: Plane Community Edition **v1.4.2**.

## Qué contiene

    plane-src/         El monorepo completo, ya con nuestras modificaciones
                       aplicadas (frontend, paquetes compartidos, Dockerfiles,
                       docker-compose). Es el árbol desde el que se construyen
                       las imágenes que sirven esta instancia.

    backend-layers/    Las capas que se aplican sobre la imagen oficial del
                       backend para producir la nuestra:
                         plane-backend-patch/   API pública (páginas, features)
                         sintergica-features/   módulos Django propios
                                                (finance, assistant, drive,
                                                wiki) y sus parches de registro

Se han omitido `node_modules/`, `.git/` y las salidas de compilación, que no son
fuente y se regeneran con las instrucciones de abajo.

## Qué NO contiene, y por qué

No incluye la configuración de esta instancia (`plane.env`, credenciales de base
de datos, claves de API, certificados) ni ningún dato de usuarios. No forman
parte del código fuente correspondiente: son datos de operación, no la obra.

## Cómo construirlo

Requisitos: Docker y Docker Compose.

    cd plane-src
    cp .env.example .env        # y complétalo con tu propia configuración
    docker compose up -d

Para reproducir exactamente las imágenes de esta instancia, las capas de backend
se aplican con los Dockerfile y los scripts `patch_*.py` incluidos en
`backend-layers/`. Cada script de parche lleva aserciones: si el fuente original
cambió y un patrón ya no encaja, la construcción falla en lugar de producir una
imagen silenciosamente rota.

## Tus derechos

La AGPL-3.0 te permite usar, estudiar, modificar y redistribuir este software.
Si lo modificas y lo ofreces a través de una red, debes ofrecer el código fuente
correspondiente de tu versión a quienes la usen.

Texto completo de la licencia: `LICENSE.txt`, o
https://www.gnu.org/licenses/agpl-3.0.txt
EOF

echo "=== 4/5 Comprobación de secretos (aborta si encuentra algo) ==="
# Falla cerrada: es preferible no publicar nada a publicar una credencial.
PATTERN='BEGIN [A-Z ]*PRIVATE KEY|sk-ant-api[0-9]{2}-|ghp_[A-Za-z0-9]{30,}|re_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}'
# Marcadores de posición documentados publicamente que NO son credenciales.
# Se comparan por valor exacto, no se relaja el patron: si aparece una clave
# real con el mismo prefijo, sigue saltando.
ALLOW='AKIAIOSFODNN7EXAMPLE'
FOUND=$(grep -rhIoE "$PATTERN" "$STAGE/$NAME" 2>/dev/null | sort -u | grep -vxF "$ALLOW" || true)
if [ -n "$FOUND" ]; then
  echo "FATAL: posibles credenciales en el paquete. NO se publica nada."
  echo "$FOUND" | while read -r m; do
    echo "  coincidencia: $m"
    grep -rIlF "$m" "$STAGE/$NAME" | sed 's|^|    en: |'
  done
  exit 1
fi
# Ficheros de entorno. Las PLANTILLAS de upstream (plane-src/deployments/*/
# variables.env) si van: son parte del fuente y solo llevan marcadores
# (change-this-key-on-deployment, access-key). Ya pasaron el escaneo de patrones
# de arriba, asi que un valor real ahi habria saltado igualmente.
# Cualquier otro .env, y siempre plane.env o deploy.env, es fatal.
ENVS=$(find "$STAGE/$NAME" \( -name '*.env' -o -name '.env' \) \
        ! -path '*/plane-src/deployments/*' ! -name '*.example*' 2>/dev/null || true)
ENVS="$ENVS$(find "$STAGE/$NAME" \( -name 'plane.env' -o -name 'deploy.env' \) 2>/dev/null || true)"
if [ -n "$(echo "$ENVS" | tr -d '[:space:]')" ]; then
  echo "FATAL: ficheros de entorno dentro del paquete. NO se publica nada."
  echo "$ENVS"
  exit 1
fi
echo "  sin hallazgos"

echo "=== 5/5 Empaquetando ==="
tar -czf "$STAGE/${NAME}.tar.gz" -C "$STAGE" "$NAME"
sha256sum "$STAGE/${NAME}.tar.gz" | awk '{print $1"  '"${NAME}"'.tar.gz"}' > "$STAGE/${NAME}.tar.gz.sha256"

mv "$STAGE/${NAME}.tar.gz" "$STAGE/${NAME}.tar.gz.sha256" "$OUT_DIR/"
# Enlace estable para que la URL del aviso de licencia no cambie en cada build.
ln -sfn "${NAME}.tar.gz" "$OUT_DIR/tequio-source-latest.tar.gz"
ln -sfn "${NAME}.tar.gz.sha256" "$OUT_DIR/tequio-source-latest.tar.gz.sha256"

# Se conservan las tres últimas versiones: quien recibió binarios de una versión
# anterior sigue teniendo derecho a SU fuente correspondiente.
ls -1t "$OUT_DIR"/tequio-source-2*.tar.gz 2>/dev/null | tail -n +4 | while read -r old; do
  rm -f "$old" "${old}.sha256"
  echo "  retirada versión antigua: $(basename "$old")"
done

rm -rf "$STAGE"
chmod -R a+rX "$OUT_DIR"
echo
echo "=== Listo ==="
ls -lh "$OUT_DIR"
