# Capa 2 — Wiki por organización + gestor de archivos

Añade a Plane CE una wiki a nivel de organización y un gestor de archivos
(por proyecto y por organización), incluyendo toda la interfaz web.

## Qué agrega

**Wiki por organización** (`/<slug>/wiki`)
- Entrada "Wiki" en el sidebar del workspace.
- Listado con pestañas Public / Private / Archived, búsqueda, orden y filtros.
- Editor colaborativo completo (el mismo de las páginas de proyecto): tiempo real
  vía servidor live (`documentType: workspace_page`), versiones, lock, acceso
  público/privado, archivar, duplicar, favoritos, imágenes embebidas.
- Backend: endpoints nuevos `/api/workspaces/<slug>/pages/...` sobre `Page.is_global=True`.
  Sin migraciones de BD.

**Gestor de archivos** (`/<slug>/drive` y `/<slug>/projects/<id>/drive`)
- Entrada "Archivos" en el sidebar del workspace y en cada proyecto.
- Subida por botón o drag & drop (múltiples archivos, barra de progreso),
  búsqueda, orden, renombrar, descargar, eliminar (solo autor o admin).
- **Previsualización**: al abrir un archivo se muestra dentro de la app
  (imágenes, PDF, vídeo, audio, texto); la descarga pasa a ser acción secundaria.
- **Enlaces externos**: se pueden registrar URLs de Google Drive (o cualquier
  http/https) como entradas más, con vista previa incrustada cuando Google lo permite.
- **Etiquetas** libres y **relación con módulos** (esto último solo en proyectos,
  porque los módulos de Plane son de proyecto).
- Los archivos van directo a MinIO con URLs prefirmadas (el backend nunca
  transporta los bytes). Modelo `FileAsset` con `entity_type="DRIVE"` — sin migraciones:
  `kind`, `url`, `tags` y `module_id` viven dentro del JSON `attributes`.
- Límite 100 MB por archivo (configurable con `DRIVE_FILE_SIZE_LIMIT`).
  El deploy sube `FILE_SIZE_LIMIT` a 100 MB para que el proxy Caddy lo permita.

### API del gestor de archivos

Base: `/api/workspaces/<slug>/drive/` y `/api/workspaces/<slug>/projects/<id>/drive/`

| Verbo | Ruta | Notas |
|---|---|---|
| GET | `/drive/` | lista de entradas |
| POST | `/drive/` | archivo: `{name,type,size,tags?,module_id?}` → URL prefirmada |
| POST | `/drive/` | enlace: `{name,kind:"link",url,tags?,module_id?}` → 201 con la entrada |
| PATCH | `/drive/<id>/` | `{name?,tags?,module_id?,url?}`; con `{}` confirma una subida |
| DELETE | `/drive/<id>/` | borrado lógico; solo autor o admin |
| GET | `/drive/<id>/` | 302 a MinIO (`attachment`); `?disposition=inline` para previsualizar |

Reglas que aplica el backend: las URLs deben ser `http(s)` (se rechazan
`javascript:`, `data:`, `file://`); las etiquetas se recortan, deduplican
sin distinguir mayúsculas y se limitan a 20 de 50 caracteres; el módulo debe
pertenecer al proyecto y no se acepta a nivel organización. Los tipos capaces
de ejecutar scripts (SVG, HTML, JS, XML) se fuerzan a descarga aunque se pida
`inline`, para evitar XSS. Para un enlace, `GET /drive/<id>/` devuelve la URL
en JSON en lugar de redirigir, de modo que el endpoint nunca sea un open redirect.

**Caveat de Google Drive**: la vista previa incrustada solo se ve si el archivo
está compartido de forma que el visor pueda abrirlo (p. ej. "cualquiera con el
enlace"); si no, Google muestra su propia pantalla de permisos dentro del marco.
El sitio no envía CSP y su `X-Frame-Options: DENY` solo impide que a Plane lo
incrusten otros, así que no bloquea estos iframes salientes.

## Contenido

```
backend/          6 archivos python: endpoints nuevos + patcher de URLs
live/             servicio y parche del servidor de colaboración en tiempo real
web-live.patch    git diff con 62 archivos (frontend web + live + traducciones)
scripts/          despliegue (ver más abajo)
verify/           pruebas funcionales que corren dentro del contenedor api
```

### Scripts

| Script | Para qué |
|---|---|
| `deploy.sh` | despliegue completo: sube el paquete y construye las 3 imágenes |
| `sync-web.sh` | sólo frontend: sincroniza archivos, reconstruye la imagen web y la recrea |
| `sync-backend.sh` | sólo backend: reconstruye la imagen del api y recrea api + workers |
| `fix-live-image.sh` | corrige la imagen del servicio `live` en el compose |

Todos leen la conexión de `scripts/deploy.env` (copia `deploy.env.example` y
complétalo; está en `.gitignore`, nunca se sube). Variables: `VPS_HOST`,
`VPS_PORT`, `VPS_KEY`, `REMOTE_SRC` y `PLANE_SRC` (ruta local al árbol de
fuentes de Plane, necesaria sólo para `sync-web.sh`).

## Notas de mantenimiento

**Tokens de diseño.** Plane v1.4.2 abandonó los tokens `custom-*` (`text-custom-text-200`,
`border-custom-border-200`…). Ya no existen, así que usarlos deja el componente sin estilo.
El vocabulario actual es `text-primary/secondary/tertiary/placeholder`, `border-subtle`,
`bg-layer-1/2`, `bg-canvas`, `bg-accent-primary`, `text-danger-primary` y la escala
`text-11/13/16`. Para botones usa `getButtonStyling("secondary", "lg")` de
`@plane/propel/button` en lugar de clases a mano.

**Traducciones.** Las cadenas del gestor de archivos viven bajo la clave `drive` de
`packages/i18n/src/locales/<idioma>/common.json` (namespace `common`, ya registrado).
Español e inglés están traducidos; el resto de idiomas hereda el inglés.

**Asistente de IA.** No es una sección del menú: en Plane CE el botón vive dentro del
editor de descripción de un *work item*, y sólo aparece si `has_llm_configured` es
verdadero y ya escribiste un título. Se configura en `/god-mode/ai/`.

## Desplegar

```bash
cp features/scripts/deploy.env.example features/scripts/deploy.env
$EDITOR features/scripts/deploy.env
bash features/scripts/deploy.sh
```

Tarda ~10–20 min (builds de web y live en el VPS). La BD, redis, minio y rabbitmq
no se tocan; el compose queda respaldado (`docker-compose.yaml.bak-<ts>`).

## Validación hecha en local (contra Plane v1.4.2)

- Backend: sintaxis python OK, anclajes del patcher verificados contra el árbol v1.4.2.
- Live: `tsc --noEmit` OK con el parche aplicado.
- Web: `react-router typegen && tsc --noEmit` OK y build de producción completo OK
  (los chunks `wiki-*.js` y `drive-*.js` presentes en el bundle).

## Revertir

En el dir del compose del VPS: restaurar `docker-compose.yaml.bak-<ts>` y
`docker compose up -d --no-deps --force-recreate api worker beat-worker web live proxy`.
En el árbol de fuentes: `git apply -R web-live.patch`.
