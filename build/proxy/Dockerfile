# Tequio · proxy (Caddy). Deriva del oficial y solo cambia el Caddyfile: añade
# la ruta /source/ que sirve el código fuente correspondiente (AGPL-3.0 §13).
#
# Esa ruta tiene que ir ANTES del catch-all `reverse_proxy /* web:3000`. Si va
# después, la SPA responde 200 con su pantalla de "no encontrado" y el enlace de
# licencia PARECE funcionar sin servir nada — comprobado en producción.
#
# Contexto de build: la RAÍZ del repositorio.
ARG BASE_PROXY_IMAGE=makeplane/plane-proxy:v1.4.2
FROM ${BASE_PROXY_IMAGE}

COPY features/source-offer/Caddyfile /etc/caddy/Caddyfile

RUN set -e; \
    grep -q 'handle_path /source/\*' /etc/caddy/Caddyfile \
      || { echo "FATAL: el Caddyfile no sirve /source/"; exit 1; }; \
    awk '/handle_path \/source\/\*/ {s=NR} /reverse_proxy \/\* web:3000/ {w=NR} \
         END { if (!s || !w || s > w) { print "FATAL: /source/ no va antes del catch-all"; exit 1 } }' \
      /etc/caddy/Caddyfile; \
    echo "OK: proxy verificado"
