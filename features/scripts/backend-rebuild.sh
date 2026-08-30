#!/bin/bash
# Se ejecuta EN el VPS. Reconstruye la imagen del backend a partir de la imagen
# OFICIAL de Plane (no de la personalizada) para que los parches no se apilen,
# y recrea api + workers.
set -euo pipefail

TAG="${1:-wiki-drive}"
FEAT_DIR="/opt/sintergica-features"
BB="$FEAT_DIR/backend-build"

cid() { docker ps -q --filter "label=com.docker.compose.service=$1" | head -1; }
API_CID=$(cid api)
[ -n "$API_CID" ] || { echo "FATAL: no encuentro el contenedor api"; exit 1; }
COMPOSE_DIR=$(docker inspect "$API_CID" --format '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}')

# La imagen base es la que ya tenía los parches de MCP/IA de antes, no la oficial:
# reconstruir sobre ella mantiene esas funciones. Los parches son idempotentes
# (patch_ce_features.py detecta si ya se aplicaron).
BASE_IMAGE="plane-backend-custom:v1.4.2-mcp"
docker image inspect "$BASE_IMAGE" >/dev/null 2>&1 || { echo "FATAL: falta la imagen base $BASE_IMAGE"; exit 1; }

mkdir -p "$BB"
cp "$FEAT_DIR/backend/"*.py "$BB/"
for app in finance assistant; do
  rm -rf "${BB:?}/$app"
  cp -r "$FEAT_DIR/backend/$app" "$BB/$app"
done
cat > "$BB/Dockerfile" <<EOF
FROM ${BASE_IMAGE}
COPY workspace_page_serializers.py /code/plane/app/serializers/workspace_page_ext.py
COPY workspace_page_views.py       /code/plane/app/views/workspace_page_ext.py
COPY workspace_page_urls.py        /code/plane/app/urls/workspace_page_ext.py
COPY drive_views.py                /code/plane/app/views/drive_ext.py
COPY drive_urls.py                 /code/plane/app/urls/drive_ext.py
COPY finance/                      /code/plane/finance/
COPY assistant/                    /code/plane/assistant/
COPY patch_ce_features.py          /tmp/patch_ce_features.py
# pypdf: extracción de texto de estados de cuenta en PDF (finanzas)
RUN pip install --no-cache-dir "pypdf>=5,<6"
RUN python /tmp/patch_ce_features.py && rm /tmp/patch_ce_features.py
EOF

echo "=== Build ==="
docker build -t "plane-backend-custom:${TAG}" "$BB"

cd "$COMPOSE_DIR"

# El compose apunta a un tag literal. Construir con OTRO tag deja la imagen
# nueva sin usar: el migrator y los contenedores siguen con la vieja y el
# despliegue parece correcto sin serlo. Pasó al añadir el asistente.
if ! grep -q "plane-backend-custom:${TAG}" docker-compose.yaml; then
  echo "FATAL: docker-compose.yaml no referencia plane-backend-custom:${TAG}."
  echo "       Tags que sí usa:"
  grep -o 'plane-backend-custom:[A-Za-z0-9._-]*' docker-compose.yaml | sort -u | sed 's/^/         /'
  echo "       Reconstruye con uno de esos, o actualiza el compose primero."
  exit 1
fi

# --- Migraciones (módulo de finanzas) ---------------------------------------
# Si la imagen trae migraciones pendientes (finance, assistant), api/worker/beat se quedan
# bloqueados en wait_for_migrations hasta que alguien corra `migrate`.
# Orden obligatorio: respaldo -> migrator -> recreate.
if ls "$BB"/*/migrations/0*.py >/dev/null 2>&1; then
  echo "=== Respaldo de la base de datos ==="
  mkdir -p "$FEAT_DIR/db-backups"
  DUMP="$FEAT_DIR/db-backups/plane-$(date +%F-%H%M%S).dump"
  # El contenedor define PGHOST=plane-db, lo que fuerza TCP y pide contraseña;
  # se pasa PGPASSWORD desde el propio entorno del contenedor.
  docker compose -f docker-compose.yaml --env-file=plane.env exec -T plane-db \
    sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$DUMP"
  ls -la "$DUMP"
  [ -s "$DUMP" ] || { echo "FATAL: el respaldo quedó vacío — no se migra"; exit 1; }

  echo "=== Aplicando migraciones (migrator) ==="
  docker compose -f docker-compose.yaml --env-file=plane.env run --rm migrator \
    || docker compose -f docker-compose.yaml --env-file=plane.env up migrator
else
  echo "(sin migraciones en el build — se omite migrator)"
fi

echo "=== Recreando api y workers ==="
docker compose -f docker-compose.yaml --env-file=plane.env up -d --no-deps --force-recreate api worker beat-worker

sleep 20
docker ps --format '{{.Label "com.docker.compose.service"}}  {{.Image}}  {{.Status}}' | grep -E "^(api|worker|beat-worker) "
