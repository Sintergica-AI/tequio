# Canales de Tequio (módulo `plane.chat`)

Sistema de canales de chat por proyecto y por workspace, estilo ClickUp Chat,
nativo dentro de Tequio (fork de Plane CE v1.4.2). **No confundir con el
producto de chat aparte** (Mattermost rebrandeado para reventa, repos `chat-*`
en Sintergica-AI): esto es una feature interna de Tequio; a mediano plazo
sustituye a Mattermost para uso interno de Sintérgica.

Estado: F1 (backend REST) desplegada y verificada 32/32 (`verify10.py`).
F2 (frontend con polling) y F3 (tiempo real vía servidor live) — código
completo; despliegue documentado abajo.

## Alcance v1

- Canales por proyecto (con `#general` automático) + canales de workspace
- Menciones `@usuario` → `Notification` (entity_name `chat_message`, sin migración upstream)
- Hilos de **un nivel** (estilo Slack: responder a una respuesta cuelga de la raíz)
- Reacciones emoji (código decimal `128077`, patrón `CommentReaction`)
- Vincular work items a mensajes (chips) y crear work item desde un mensaje
- Tiempo real por websocket con **fallback a polling** transparente
- Fuera de v1: DMs, adjuntos, canales privados (campo `access` reservado)

## Arquitectura

```
navegador ──REST──────────────▶ Django (plane.chat)  ← fuente de verdad (Postgres)
    │                              │ celery: chat_event_task / chat_message_notify_task
    │                              ▼ POST /live/broadcast  (live-server-secret-key)
    └──WS (Hocuspocus)──▶ apps/live ──Redis pub/sub──▶ todos los clientes del canal
       documentType=channel        (documentName "chat:<channel_id>")
```

Decisiones clave (y por qué):

- **El Y.Doc de un canal está vacío a propósito.** El socket solo transporta
  eventos stateless JSON + awareness (presencia/escribiendo). Guardar historial
  en el CRDT sería un mal ajuste: debounce de 10 s en persistencia, tope 413,
  crecimiento sin límite. Postgres manda; el WS solo empuja.
- **Membresía implícita.** Canal de workspace = cualquier miembro activo del
  workspace; canal de proyecto = cualquier `ProjectMember` activo (invitados
  incluidos — chat es comunicación). `ChannelMember` es SOLO estado personal
  (last_read_at, mute), creado lazy. Todo query pasa por `channel_queryset()`:
  un canal fuera de alcance da 404, no 403 (sin fuga de existencia).
- **Autorización del WS explícita.** `onAuthenticate` del live solo valida
  identidad; en pages la autorización la pone Django al servir el binario. Un
  canal no toca ese camino, así que `fetchDocument` para `"channel"` llama a
  `GET .../channels/<id>/membership/` con la cookie del usuario antes de
  aceptar el doc (`chat-channel.service.ts`). Sin ese guard, cualquier usuario
  autenticado podría escuchar cualquier canal.
- **Broadcast best-effort.** Si el push al live falla (endpoint caído, secret
  ausente), se loguea warning y ya: los clientes tienen catch-up
  `created_at__gt` en cada reconexión Y polling de respaldo cuando
  `isLive === false`. Un mensaje nunca se pierde, solo tarda.
- **Envío optimista con dedup.** El cliente pinta un id `temp-*`, lo sustituye
  por la fila real al ack; `applyIncomingEvent` ignora ids ya conocidos, así
  el eco del propio mensaje por WS es no-op.
- **Borrado con lápida.** Borrar una raíz con respuestas vivas conserva la
  fila (`is_removed=True`, contenido vaciado) para que el hilo no quede
  huérfano; se difunde como `message.updated`. Sin respuestas → soft-delete y
  `message.deleted`.

## Backend (`features/backend/chat/`)

5 tablas (todas `BaseModel`, aditivas): `chat_channels`, `chat_channel_members`,
`chat_messages`, `chat_message_reactions`, `chat_message_work_items`.
Endpoints bajo `/api/workspaces/<slug>/chat/` (cookie de sesión, decorador
`@allow_chat`): canales CRUD, `membership/` (lo consume el live), `messages/`
con cursor keyset `(created_at, id)` y catch-up `?created_at__gt=`, `thread/`,
`reactions/`, `read/`, `unreads/` (una query agregada), `work-items/`.

Trampas que costaron un ciclo cada una:

- **`assistant.Message` y `chat.Message` chocan**: el `related_name`
  `%(class)s_created_by` de BaseModel usa el nombre de CLASE. La clase se
  llama `ChatMessage` (la tabla sigue siendo `chat_messages`). Cualquier
  módulo nuevo debe evitar nombres de clase ya usados por otros módulos
  propios.
- **La migración 0001 se GENERA dentro de la imagen**, no se escribe a mano:
  Django deconstruye los kwargs de `Q()` en los constraints en orden distinto
  al escrito y `--check` acusa un falso "cambio". Flujo: construir imagen →
  `manage.py makemigrations chat` en un contenedor efímero → copiar el archivo
  → **fijar la dependencia a `db.0122`** (el generador apunta a
  `db.0123_alter_profile_language`, que es la divergencia deliberada del parche
  de idioma y NO existe como archivo).
- **`makemigrations --check` global acusa el parche de idioma.** La compuerta
  de `backend-rebuild.sh` valida SOLO `finance assistant chat`.
- **`+00:00` en query strings llega como espacio** si el cliente no urlencodea.
  `_parse_ts()` repone el `+` antes de `parse_datetime` (sin eso, cursor y
  catch-up devuelven 400 con clientes ingenuos).

## Frontend (`apps/web`, viaja en `web-live.patch`)

Rutas `/:slug/channels(/:id)` y `/:slug/projects/:pid/channels(/:id)`
(`extended.ts`). Store MobX `chat.store.ts` (registrado en root.store en DOS
sitios), service, hook `useChat`. UI propia en `core/components/chat/` (en
`OWNED_DIRS` de sync-web.sh) — se importan sin copiar `LiteTextEditor`
(menciones, Enter envía), `EmojiReactionGroup/Picker` de propel,
`ExistingIssuesListModal` y `CreateUpdateIssueModal` (crear WI desde mensaje,
prellenado con el stripped). i18n completo en los 19 locales (ICU single-brace).

Realtime del cliente: `use-channel-connection.ts` — HocuspocusProvider contra
`?documentType=channel&workspaceSlug=...`, token `{"id": <user_id>}` (la
cookie va en los headers del WS same-origin), eventos por `onStateless`,
typing/presencia por awareness con TTL de 5 s. Polling (10 s canal activo,
60 s unreads) SOLO cuando `isLive === false`.

## Live (`features/live/`)

`patch_live_features.py` añade: documentType `"channel"`, early-returns en
`database.ts` (fetch = gate de autorización + `Uint8Array(0)`; store = no-op),
guard en `title-sync.ts`, y registra `chat.controller.ts`
(`POST /broadcast`, protegido con `live-server-secret-key`, fan-out por la
extensión Redis con fallback local). Los patches **encadenan sobre las cadenas
ya parcheadas** de workspace_page — el orden importa.

Django → live: `chat/realtime.py`. `settings.LIVE_URL` es **None** en este
despliegue (LIVE_BASE_URL sin definir); el default es la dirección interna del
compose `http://live:3000/live`, verificada alcanzable desde el contenedor
api. El secret ya estaba en el entorno del api (mismo plane.env).

## Despliegue

Orden F3: **live → backend → web** (el live debe aceptar el tipo y el endpoint
antes de que Django empuje; el web con hook contra un live viejo degrada solo
a polling, no rompe).

- Backend: `sync-backend.sh wiki-drive` (compuerta makemigrations, pg_dump,
  migrator, recreate). Verify: `verify10.py` en el contenedor api (32 checks).
- Live: `sync-live.sh wiki-drive` (nuevo; git-status sobre apps/live +
  aserciones de contenido + build + recreate). Verify: `verify11.py`.
- Web: `sync-web.sh wiki-drive`. **Gotcha corregido el 30 Ago**: el build iba
  en un pipe a `tail` y un fallo pasaba en silencio recreando la imagen vieja;
  ahora el exit del build aborta el script. Segundo gotcha del mismo día: los
  archivos se copian con la lista de `git status` tomada AL INICIO — editar el
  árbol con un sync en vuelo produce estados remotos mixtos (lockfile nuevo +
  package.json viejo = frozen-lockfile roto). No editar plane-src con un sync
  corriendo.
- Tras cada deploy: regenerar tarball AGPL (`build-source-tarball.sh` en el
  VPS) y, al commitear, `regen-patch.sh`.

## Verificación E2E (F3)

Dos navegadores con usuarios distintos en el mismo canal: el mensaje aparece
en <1 s sin refrescar; "escribiendo…" visible; matar el contenedor live → la
UI degrada a polling (10 s); revivirlo → reconexión + catch-up sin huecos ni
duplicados (dedup por id).
