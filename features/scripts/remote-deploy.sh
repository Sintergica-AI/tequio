#!/bin/bash
# Sintergica: despliega la wiki por organización y el gestor de archivos (drive)
# en el Plane self-hosted. Se ejecuta EN el VPS desde /opt/sintergica-features.
set -euo pipefail

FEAT_DIR="/opt/sintergica-features"
SRC_DIR="/opt/plane-src"
TAG="wiki-drive"

echo "=== 1/6 Localizando la instalación de Plane ==="
cid() { docker ps -q --filter "label=com.docker.compose.service=$1" | head -1; }
API_CID=$(cid api); WEB_CID=$(cid web); LIVE_CID=$(cid live)
[ -n "$API_CID" ] && [ -n "$WEB_CID" ] && [ -n "$LIVE_CID" ] || { echo "FATAL: no encuentro los contenedores api/web/live"; exit 1; }
COMPOSE_DIR=$(docker inspect "$API_CID" --format '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}')
[ -d "$COMPOSE_DIR" ] || { echo "FATAL: no se encontró el directorio de compose"; exit 1; }
cd "$COMPOSE_DIR"
CUR_API_IMAGE=$(docker inspect "$API_CID" --format '{{ .Config.Image }}')
CUR_WEB_IMAGE=$(docker inspect "$WEB_CID" --format '{{ .Config.Image }}')
CUR_LIVE_IMAGE=$(docker inspect "$LIVE_CID" --format '{{ .Config.Image }}')
echo "compose: $COMPOSE_DIR"
echo "api:  $CUR_API_IMAGE"
echo "web:  $CUR_WEB_IMAGE"
echo "live: $CUR_LIVE_IMAGE"
cp docker-compose.yaml "docker-compose.yaml.bak-$(date +%s)"

echo "=== 2/6 Backend: imagen derivada de la actual ==="
BB="$FEAT_DIR/backend-build"
mkdir -p "$BB"
cp "$FEAT_DIR/backend/"*.py "$BB/"
cat > "$BB/Dockerfile" <<EOF
FROM ${CUR_API_IMAGE}
COPY workspace_page_serializers.py /code/plane/app/serializers/workspace_page_ext.py
COPY workspace_page_views.py       /code/plane/app/views/workspace_page_ext.py
COPY workspace_page_urls.py        /code/plane/app/urls/workspace_page_ext.py
COPY drive_views.py                /code/plane/app/views/drive_ext.py
COPY drive_urls.py                 /code/plane/app/urls/drive_ext.py
COPY patch_ce_features.py          /tmp/patch_ce_features.py
RUN python /tmp/patch_ce_features.py && rm /tmp/patch_ce_features.py
EOF
docker build -t "plane-backend-custom:${TAG}" "$BB"

echo "=== 3/6 Web + Live: aplicar parche de código ==="
cd "$SRC_DIR"
if git apply --check "$FEAT_DIR/web-live.patch" 2>/dev/null; then
  git apply "$FEAT_DIR/web-live.patch"
  echo "parche aplicado con git apply"
elif git apply --reverse --check "$FEAT_DIR/web-live.patch" 2>/dev/null; then
  echo "parche ya estaba aplicado — continuo"
else
  echo "git apply falló; intentando patch -p1 con rechazos visibles"
  patch -p1 --forward < "$FEAT_DIR/web-live.patch" || {
    echo "FATAL: el parche no aplica limpio. Revisa los .rej en $SRC_DIR"; exit 1; }
fi

echo "=== 4/6 Build de imágenes web y live (tarda ~10-20 min) ==="
docker build -f apps/web/Dockerfile.web -t "plane-web-custom:${TAG}" . 2>&1 | tail -5
docker build -f apps/live/Dockerfile.live -t "plane-live-custom:${TAG}" . 2>&1 | tail -5

echo "=== 5/6 Actualizar compose y límite de subida ==="
cd "$COMPOSE_DIR"
python3 - "$CUR_API_IMAGE" "$CUR_WEB_IMAGE" "$CUR_LIVE_IMAGE" "$TAG" <<'PYEOF'
import re, sys
cur_api, cur_web, cur_live, tag = sys.argv[1:5]
p = "docker-compose.yaml"
c = open(p).read()

# Ojo: los servicios que aún no se han personalizado traen la imagen en forma de
# variable ("makeplane/plane-live:${APP_RELEASE:-v1.4.2}"), no el nombre resuelto
# que devuelve docker inspect. Sustituir sólo el nombre resuelto es un no-op
# silencioso, así que aquí se compara también contra la forma con variable y se
# aborta si alguna sustitución no ocurre.
def swap(content, current, new_image):
    if f"image: {new_image}" in content:
        print(f"  ya estaba: {new_image}")
        return content
    candidates = [current]
    m = re.match(r"^(.*?):([\w.\-]+)$", current)
    if m:
        candidates.append(f"{m.group(1)}:${{APP_RELEASE:-{m.group(2)}}}")
    for cand in candidates:
        if f"image: {cand}" in content:
            print(f"  {cand} -> {new_image}")
            return content.replace(f"image: {cand}", f"image: {new_image}", 1)
    raise SystemExit(f"FATAL: no se encontró la imagen de {current} en el compose")

c = swap(c, cur_api, f"plane-backend-custom:{tag}")
c = swap(c, cur_web, f"plane-web-custom:{tag}")
c = swap(c, cur_live, f"plane-live-custom:{tag}")
open(p, "w").write(c)
print("compose actualizado")
PYEOF
# verificación: los tres servicios deben apuntar a las imágenes nuevas
for img in "plane-backend-custom:$TAG" "plane-web-custom:$TAG" "plane-live-custom:$TAG"; do
  grep -q "image: $img" docker-compose.yaml || { echo "FATAL: $img no quedó en el compose"; exit 1; }
done
echo "compose verificado"
# límite de subida a 100 MB (Caddy interno + Django). Sin esto el proxy corta en 5 MB.
if grep -q "^FILE_SIZE_LIMIT=" plane.env; then
  sed -i "s/^FILE_SIZE_LIMIT=.*/FILE_SIZE_LIMIT=104857600/" plane.env
else
  echo "FILE_SIZE_LIMIT=104857600" >> plane.env
fi
# aviso si hay un proxy externo nginx que también limite el body
if [ -d /etc/nginx ] && grep -rql "plane" /etc/nginx/sites-enabled 2>/dev/null; then
  grep -rq "client_max_body_size" /etc/nginx/sites-enabled || \
    echo "AVISO: nginx externo sin client_max_body_size — agrega 'client_max_body_size 110m;' al site de plane y recarga nginx"
fi

echo "=== 6/6 Recrear servicios (BD/redis/minio intactos) ==="
docker compose -f docker-compose.yaml --env-file=plane.env up -d --no-deps --force-recreate api worker beat-worker web live proxy

echo "--- Verificación ---"
sleep 20
docker compose -f docker-compose.yaml --env-file=plane.env ps | head -15
echo "Wiki API:"
curl -s -o /dev/null -w "  GET /api/workspaces/sintergica/pages/ -> HTTP %{http_code} (401/403 = ruta viva, falta sesión)\n" \
  http://localhost/api/workspaces/sintergica/pages/ || true
echo "Drive API:"
curl -s -o /dev/null -w "  GET /api/workspaces/sintergica/drive/ -> HTTP %{http_code} (401/403 = ruta viva, falta sesión)\n" \
  http://localhost/api/workspaces/sintergica/drive/ || true
echo "LISTO. Abre https://plane.sintergica.ai — sidebar: Wiki y Archivos."
