#!/bin/bash
# Corrige la imagen del servicio `live` en el compose y recrea el contenedor.
# El script de deploy original falló aquí: buscaba la forma resuelta
# "makeplane/plane-live:v1.4.2" pero el compose usa la forma con variable
# "${APP_RELEASE:-v1.4.2}", así que la sustitución fue un no-op silencioso.
set -euo pipefail

cd /opt/plane/plane-app
cp docker-compose.yaml "docker-compose.yaml.bak-livefix-$(date +%s)"

python3 - <<'PYEOF'
p = "docker-compose.yaml"
c = open(p).read()
new = "image: plane-live-custom:wiki-drive"
if new in c:
    print("live ya apuntaba a la imagen nueva")
else:
    old = "image: makeplane/plane-live:${APP_RELEASE:-v1.4.2}"
    assert old in c, "FATAL: no se encontro la linea de imagen de live"
    c = c.replace(old, new, 1)
    open(p, "w").write(c)
    print("OK: live ->", new)
PYEOF

echo "=== imagenes en compose ==="
grep -n "image:" docker-compose.yaml

echo "=== recreando live ==="
docker compose -f docker-compose.yaml --env-file=plane.env up -d --no-deps --force-recreate live

sleep 15
echo "=== estado ==="
docker ps --format '{{.Label "com.docker.compose.service"}}  {{.Image}}  {{.Status}}' | grep -E "^(web|api|live|worker|beat-worker|proxy) "
