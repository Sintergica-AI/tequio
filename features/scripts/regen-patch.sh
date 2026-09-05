#!/bin/bash
# Regenera features/web-live.patch, que es como el frontend viaja al repo.
#
# POR QUE ESTE SCRIPT EXISTE, en vez de un comando para pegar en la terminal:
#
# 1. zsh. El comando documentado era
#        git diff HEAD -- $PATHS
#    con las rutas en una variable. En bash eso se divide en palabras; en zsh NO:
#    git recibe la lista entera como UN pathspec, no encuentra nada, y escribe un
#    parche VACIO con codigo de salida 0. El shell interactivo de macOS es zsh,
#    asi que pegar el comando en una terminal borra el parche sin avisar.
#    Aqui las rutas van en un array y se expanden con "${PATHS[@]}".
#
# 2. HEAD. plane-src es un clon de upstream en HEAD desacoplado sobre v1.4.2 y
#    ahi NO se commitea nunca. Si alguien commitea, `git diff HEAD` queda vacio
#    y el parche se regenera vacio, tambien en silencio.
#
# 3. La lista de rutas se queda corta cuando el arbol crece. Ya paso cuatro veces:
#    apps/admin fuera de sync-web.sh; apps/space y packages/propel fuera del
#    patch (los logotipos viven en propel: sin el, el rebranding sale a medias);
#    y packages/types y packages/utils fuera del patch (ahi viven el tipo de las
#    claves de configuracion de instancia y los criterios de contrasena, asi que
#    sin ellos la pantalla de alta compila pero se ve a medio traducir y la
#    clave nueva del proveedor de IA ni siquiera tipa).
#
# Las tres fallan en silencio, asi que el resultado se verifica solo. Si una
# asercion salta, NO se toca el parche existente.
set -euo pipefail

SRC="$(cd "$(dirname "$0")/../plane-src" && pwd)"
OUT="$(cd "$(dirname "$0")/../plane-ce-api-extension" && pwd)/features/web-live.patch"
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

PATHS=(
  apps/web apps/admin apps/space apps/live
  packages/constants packages/editor packages/i18n packages/propel
  packages/types packages/utils
  pnpm-lock.yaml
)
# Minimos esperados por directorio. No son cifras magicas: son "si esto baja de
# aqui, algo se quedo fuera". Subirlos cuando el arbol crezca de verdad.
declare -a MIN_DIRS=(packages/propel:5 apps/space:10 apps/admin:50 apps/web:200 packages/i18n:100 packages/types:1 packages/utils:1)
MIN_TOTAL=400

cd "$SRC"

if ! git rev-parse --verify HEAD >/dev/null 2>&1; then
  echo "FATAL: no hay HEAD en $SRC"; exit 1
fi
# El arbol tiene que estar sobre el tag de upstream: si alguien commiteo aqui,
# el diff contra HEAD ya no representa nuestras modificaciones.
if [ -n "$(git branch --show-current)" ]; then
  echo "AVISO: plane-src esta en una rama ($(git branch --show-current)), no en HEAD desacoplado."
  echo "       Si se commiteo aqui, el parche saldra incompleto. Revisalo antes de seguir."
fi

# `add -N` expande los directorios nuevos que git colapsa a "?? dir/".
git add -A -N -- "${PATHS[@]}" >/dev/null 2>&1 || true
# --binary: sin el, los assets (favicons, og-images, media del login) salen como
# "Binary files differ" y el repo no puede reproducir el arbol. git apply los
# aplica sin problema; el fallback patch(1) de remote-deploy.sh no los entiende,
# pero ese fallback solo corre cuando git apply fallo, y ahi ya hay que mirar.
git diff --binary HEAD -- "${PATHS[@]}" > "$TMP"

N=$(grep -c "^diff --git" "$TMP" || true)
if [ "$N" -lt "$MIN_TOTAL" ]; then
  echo "FATAL: el parche tiene $N archivos, se esperaban al menos $MIN_TOTAL."
  echo "       El parche existente NO se ha tocado."
  echo "       Causas tipicas: se commiteo en plane-src, o el shell no dividio las rutas."
  exit 1
fi

# Fondo, no solo forma: las cabeceras "diff --git" existen aunque el contenido
# binario falte. Si alguien quita --binary, esto falla en vez de escribir un
# parche que parece bueno. (Propuesto por la sesion -22 tras encontrar 31
# activos vacios en el parche que ella misma commiteo.)
B=$(grep -c "^Binary files .* differ$" "$TMP" || true)
[ "$B" -eq 0 ] || { echo "FATAL: $B binarios sin contenido; falta --binary. El parche existente NO se ha tocado."; exit 1; }

FAIL=0
for entry in "${MIN_DIRS[@]}"; do
  d="${entry%:*}"; min="${entry#*:}"
  c=$(grep -c " b/$d" "$TMP" || true)
  if [ "$c" -lt "$min" ]; then
    echo "FATAL: $d aparece $c veces, se esperaban al menos $min."
    FAIL=1
  else
    printf "  %-22s %5d\n" "$d" "$c"
  fi
done
[ "$FAIL" -eq 0 ] || { echo "El parche existente NO se ha tocado."; exit 1; }

mv "$TMP" "$OUT"
trap - EXIT
echo "  ---"
echo "  OK: $N archivos, $(du -h "$OUT" | cut -f1) -> $OUT"
