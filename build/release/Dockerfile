# Tequio · imagen de RELEASE. No corre nada: es el punto de sincronía de un
# despliegue y el vehículo de tres cosas que tienen que viajar juntas y no
# pueden desfasarse entre sí:
#
#   /release.json  qué versión es
#   /kit/          instalador, compose, comandos y unidades de systemd
#   /source/       el código fuente correspondiente (AGPL §13) de ESTA versión
#
# CI la publica AL FINAL, cuando las seis imágenes de la versión ya están en el
# registro. Por eso el actualizador solo mira esta: si existe con la etiqueta
# del canal, todo lo demás existe. Mover `:stable` es el interruptor de un
# despliegue, y es atómico.
FROM alpine:3.22

ARG VERSION
ARG CHANNEL

LABEL ai.sintergica.tequio.version="${VERSION}" \
      ai.sintergica.tequio.channel="${CHANNEL}" \
      org.opencontainers.image.title="Tequio release" \
      org.opencontainers.image.vendor="Sintergica AI" \
      org.opencontainers.image.licenses="AGPL-3.0-only"

COPY kit/    /kit/
COPY source/ /source/
COPY release.json /release.json

RUN set -e; \
    [ -n "${VERSION}" ] || { echo "FATAL: build sin VERSION"; exit 1; }; \
    [ -x /kit/bin/tequio-update ] || { echo "FATAL: el kit no trae un actualizador ejecutable"; exit 1; }; \
    [ -x /kit/bin/tequio ] || { echo "FATAL: el kit no trae el comando tequio"; exit 1; }; \
    [ -f /kit/docker-compose.yaml ] || { echo "FATAL: el kit no trae el compose"; exit 1; }; \
    [ -f /kit/tequio.env.example ] || { echo "FATAL: el kit no trae la plantilla de entorno"; exit 1; }; \
    [ -f /kit/install.sh ] || { echo "FATAL: el kit no trae el instalador"; exit 1; }; \
    [ -f "/source/tequio-source-${VERSION}.tar.gz" ] \
      || { echo "FATAL: falta el tarball de fuente de ${VERSION}"; exit 1; }; \
    grep -q "\"version\": \"${VERSION}\"" /release.json \
      || { echo "FATAL: release.json no declara ${VERSION}"; exit 1; }; \
    echo "OK: release ${VERSION} (${CHANNEL})"

CMD ["cat", "/release.json"]
