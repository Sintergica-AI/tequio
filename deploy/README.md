# Desplegar Tequio en el VPS de un cliente

Una instancia de Tequio se instala con un comando y a partir de ahí se actualiza
sola: cada madrugada comprueba si hay versión nueva en su canal, respalda la base
de datos, migra, recrea los servicios y —si la instancia no responde— vuelve a la
versión anterior.

El servidor **no compila nada**. Todo se construye una vez en CI y se publica
como imágenes; el VPS solo descarga. Eso quita del medio el modo de fallo que más
ha dolido en este proyecto: copiar cientos de ficheros por SSH a mitad de un
despliegue y quedarse en un estado mixto silencioso.

---

## Requisitos del servidor

- Linux con **systemd** y **Docker Engine + plugin `docker compose` v2**.
- 4 vCPU y 8 GB de RAM como mínimo cómodo (arranca con 4 GB, va justo).
- 40 GB de disco: las imágenes ocupan ~3 GB y los respaldos se acumulan.
- Puertos **80 y 443** libres y abiertos.
- Un **registro DNS A** apuntando a la IP del servidor **antes** de instalar:
  Caddy pide el certificado en el primer arranque.

## Instalar

```bash
docker run --rm ghcr.io/sintergica-ai/tequio-release:stable cat /kit/install.sh > install.sh
sudo bash install.sh --domain tequio.cliente.com --email admin@cliente.com
```

El instalador genera los secretos, escribe `/opt/tequio/tequio.env`, instala el
temporizador de actualizaciones y hace el primer despliegue. Tarda lo que tarde
la descarga de imágenes.

Al terminar:

| | |
|---|---|
| Aplicación | `https://tequio.cliente.com` |
| Panel de instancia | `https://tequio.cliente.com/god-mode/` |
| Código fuente (AGPL §13) | `https://tequio.cliente.com/source/` |

Lo primero en el panel es **configurar el correo saliente** (`/god-mode/email/`):
sin correo no salen invitaciones ni enlaces de acceso.

> **Ojo con el interruptor de correo del panel**: apagar el correo no solo lo
> desactiva, **borra** host, puerto, usuario, contraseña y remitente. Y el botón
> de "enviar correo de prueba" lee la configuración **guardada**, no lo que hay
> en el formulario: guarda antes de probar.

## Operar

```bash
tequio status      # versión, servicios, salud y cuándo toca la próxima actualización
tequio update      # aplicar ya la versión nueva, sin esperar a la madrugada
tequio doctor      # comprobaciones: claves, migraciones, disco, respaldos, fuente
tequio logs api    # seguir los registros de un servicio
tequio backup      # respaldo manual de la base de datos
tequio rollback    # volver a la versión anterior
```

Los respaldos van a `/opt/tequio/backups` (se conservan 10) y los registros de
cada actualización a `/var/log/tequio/`.

## Cómo funcionan las actualizaciones

```
  repo (main)  --etiqueta v*-->  CI construye 6 imágenes  -->  ghcr.io
                                            |
                                  publica tequio-release:stable  <- interruptor
                                            |
   VPS del cliente, 03:00 (+/- 1h)  ---->  ve la versión nueva
                                            |
      descarga  ->  respalda BD  ->  migrator  ->  recrea  ->  comprueba salud
                                                                  |
                                                       si no responde: revierte
```

**El interruptor es la etiqueta de canal de `tequio-release`**, que CI publica
al final, cuando las seis imágenes de la versión ya están arriba. Las demás
imágenes solo llevan su etiqueta de versión exacta, así que una instancia nunca
puede quedarse con mitades de dos releases.

Canales:

| Canal | Qué recibe | Para quién |
|---|---|---|
| `stable` | solo versiones etiquetadas `v*` | clientes |
| `edge` | cada cambio en `main` | la instancia de pruebas de Sintergica |

Se cambia con `TEQUIO_CHANNEL` en `tequio.env`.

### Lo que la actualización hace sola, y lo que no

Revierte sola: si tras recrear los servicios la instancia no responde en 150 s,
vuelve a la versión anterior y lo comprueba.

**No** restaura la base de datos sola. Si el `migrator` falla, se detiene sin
recrear nada —la instancia sigue con la versión anterior— y deja en el log el
comando exacto de restauración. Un `pg_restore` automático es destructivo y
tiraría lo que se haya escrito mientras tanto; las migraciones de Tequio son
aditivas por convención, así que lo normal es que la versión anterior siga
funcionando sobre el esquema nuevo. Esa decisión la toma una persona.

Corolario para quien desarrolla: **las migraciones tienen que seguir siendo
aditivas y compatibles hacia atrás**. Una migración destructiva rompe la
reversión automática, que es lo único que protege a los clientes de noche.

## La oferta de código fuente (AGPL-3.0 §13)

Tequio deriva de Plane, que es AGPL. Cualquiera que use la instancia por la red
tiene derecho al código fuente correspondiente **de la versión que está
corriendo**.

Aquí eso no es un paso manual que se olvida: el tarball se construye en CI con
las mismas entradas que las imágenes, viaja dentro de la imagen de release y el
actualizador lo publica en `/source/` en la misma operación en la que despliega
los binarios. `tequio source` comprueba que lo publicado corresponde a lo
desplegado, y `tequio doctor` falla si no.

## Publicar una versión (lado Sintergica)

```bash
git tag v2026.09.10 && git push origin v2026.09.10
```

Eso construye las seis imágenes, el tarball de fuente y la imagen de release, y
mueve `tequio-release:stable`. Los clientes lo aplican esa madrugada.

Un push a `main` sin etiqueta hace lo mismo contra el canal `edge`, que es lo que
sigue la instancia de pruebas.

### La primera vez

1. **Habilitar Actions** en el repositorio (es privado; Actions funciona igual).
2. Lanzar el workflow una vez (un push a `main` basta) para que se creen los
   paquetes en GHCR.
3. **Hacer públicos los siete paquetes** en *Organization → Packages → \<paquete\>
   → Package settings → Change visibility*: `tequio-backend`, `-web`, `-space`,
   `-admin`, `-live`, `-proxy` y `-release`. Sin esto, cada VPS de cliente
   necesita un token de lectura en su `tequio.env` (ver "Registro de imágenes").
4. Etiquetar la primera versión estable.

### Antes de etiquetar

La reversión automática de los clientes solo protege de un arranque fallido. No
protege de una migración destructiva ni de un cambio que rompa datos. Lo que hay
que comprobar en `edge` antes de mover `stable`:

- que las migraciones nuevas son **aditivas** (nada de borrar o renombrar
  columnas con datos),
- que la instancia de pruebas lleva un rato con la versión y `tequio doctor`
  sale limpio,
- que el bundle servido trae de verdad lo que se cambió — CI lo comprueba para
  el rebranding y el enlace de fuente, pero no conoce tu cambio.

## Adoptar una instancia existente

Una instalación anterior (la de `/opt/plane/plane-app`, con imágenes construidas
en el propio servidor) se puede pasar a este kit **sin perder los datos**,
porque los volúmenes se conservan si el proyecto de compose mantiene su nombre.

1. `docker compose -f docker-compose.yaml --env-file plane.env ps` en el
   directorio viejo y anota el nombre del proyecto (`docker inspect` de un
   contenedor, etiqueta `com.docker.compose.project`) y los volúmenes.
2. Respalda la base **antes de nada**:
   `docker compose exec -T plane-db sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > /root/pre-adopcion.dump`
3. Instala el kit **sin desplegar**: corre el instalador con `--home /opt/tequio`
   y, cuando escriba `tequio.env`, cópiale de `plane.env` los valores que ya
   existen: `SECRET_KEY`, `LIVE_SERVER_SECRET_KEY`, `POSTGRES_PASSWORD`,
   `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `RABBITMQ_PASSWORD`.
   **Si generas secretos nuevos, la instancia no podrá leer sus propios datos.**
4. Pon `COMPOSE_PROJECT_NAME` con el nombre del proyecto viejo: es lo que hace
   que compose reutilice `<proyecto>_pgdata`, `<proyecto>_uploads`, etc.
5. Para los contenedores viejos (`docker compose stop`) y lanza `tequio update`.
6. `tequio doctor`.

El paso que se salta la gente es el 4: con otro nombre de proyecto, compose crea
volúmenes vacíos y la instancia arranca **perfectamente, sin datos**. Se ve como
una instalación nueva, no como un error.

## Registro de imágenes

Por defecto las imágenes son públicas en `ghcr.io/sintergica-ai/`, así que la
instalación y las actualizaciones no necesitan credenciales. Es coherente con la
licencia: la AGPL ya obliga a publicar el fuente a cualquier usuario de la
instancia, así que los binarios no aportan secreto ninguno.

Si prefieres cerrarlas, hazlas privadas en la configuración de paquetes de la
organización y rellena en cada `tequio.env`:

```
TEQUIO_REGISTRY_USER=<usuario o cuenta de máquina>
TEQUIO_REGISTRY_TOKEN=<token con read:packages>
```

El actualizador hace `docker login` con eso antes de descargar nada.

## Cuando algo va mal

| Síntoma | Dónde mirar |
|---|---|
| No hubo actualización esta noche | `systemctl status tequio-update.timer`, `journalctl -u tequio-update` |
| La actualización falló | el último fichero de `/var/log/tequio/` |
| Certificado no emitido | `tequio logs proxy` — casi siempre es que el DNS no apunta aquí |
| Subidas que fallan por tamaño | `FILE_SIZE_LIMIT` y `DRIVE_FILE_SIZE_LIMIT` tienen que ir acompasados |
| La instancia responde pero un módulo no | `tequio doctor` (migraciones sin aplicar) |
