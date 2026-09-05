# Oferta de código fuente (AGPL-3.0 §13)

> **Esto describe la instalación manual del VPS propio.** En las instancias
> desplegadas con el kit de [`deploy/`](../../deploy/), las tres piezas ya vienen
> puestas y el tarball lo publica el actualizador en cada despliegue: no hay paso
> suelto que olvidar. Sigue leyendo solo si operas una instancia anterior a ese
> kit (tequio.sintergica.ai mientras no se adopte).

Tequio es una versión modificada de Plane. La AGPL obliga a que **toda persona
que use la instancia a través de la red** pueda obtener el código fuente
correspondiente de esa versión. Esto es lo que lo implementa.

## Las tres piezas

| Pieza | Dónde vive | Qué hace |
|---|---|---|
| `build-source-tarball.sh` | se ejecuta en el VPS | Empaqueta el fuente desde el árbol realmente desplegado y lo deja en `/opt/plane-source-offer/public/` |
| `Caddyfile` | se monta en el contenedor `proxy` | Sirve ese directorio en `/source/`, **antes** del catch-all de la SPA |
| `VITE_SOURCE_CODE_URL` | variable de build del web | Hace aparecer el enlace "Código fuente" en el menú de ayuda |

Las tres tienen que estar. Con dos de tres el resultado es peor que con ninguna:
un aviso de licencia que apunta a algo inaccesible afirma un cumplimiento que no
se está dando.

## Por qué el enlace no tiene valor por defecto

`SOURCE_CODE_URL` en `packages/constants/src/metadata.ts` está deliberadamente
vacío, y el item del menú solo se renderiza si hay valor. Motivo, comprobado:
el proxy termina en `reverse_proxy /* web:3000`, así que **cualquier** ruta
inexistente devuelve HTTP 200 con el HTML de la SPA. Se midió:

    /source                  HTTP 200  6846 B
    /ruta-que-no-existe-xyz  HTTP 200  6846 B
    /                        HTTP 200  6846 B

Un enlace roto ahí no falla: carga la pantalla de "no encontrado" como si
funcionara. Por eso la ruta de Caddy va antes del catch-all, y por eso el enlace
no aparece hasta que alguien define la variable a conciencia.

## Instalación (una sola vez)

1. Copiar el script y el Caddyfile al VPS:

       scp build-source-tarball.sh root@VPS:/opt/plane-source-offer/
       scp Caddyfile               root@VPS:/opt/plane-source-offer/

2. Generar el primer tarball:

       ssh root@VPS 'bash /opt/plane-source-offer/build-source-tarball.sh'

3. Montar en el servicio `proxy` del `docker-compose.yaml` (con copia de
   seguridad del compose antes):

       volumes:
         - proxy_config:/config
         - proxy_data:/data
         - /opt/plane-source-offer/Caddyfile:/etc/caddy/Caddyfile:ro
         - /opt/plane-source-offer/public:/srv/source:ro

4. Recrear el proxy y comprobar que `/source/` lista el tarball y que una ruta
   inventada sigue devolviendo la SPA (es decir, que no se rompió el catch-all).

5. Definir `VITE_SOURCE_CODE_URL=https://plane.sintergica.ai/source/` en la
   configuración de build del web y reconstruir la imagen web. **La variable se
   hornea en el bundle**: no basta con ponerla en el entorno del contenedor.

## Mantenimiento

Regenerar el tarball **después de cada despliegue que cambie el código**, o el
fuente ofrecido deja de corresponder a los binarios servidos. Se conservan las
tres últimas versiones a propósito: quien usó una versión anterior conserva el
derecho a *su* fuente correspondiente.

El empaquetado usa **lista blanca de rutas, no exclusiones**. `/opt/sintergica-features`
contiene `db-backups/` con datos reales de clientes y ficheros de entorno con
credenciales. Una lista negra se rompe en silencio en cuanto aparece un
directorio nuevo; la blanca falla cerrada. Además el script aborta si detecta
claves privadas, tokens o ficheros `.env` dentro del paquete. No lo conviertas
en lista negra.
