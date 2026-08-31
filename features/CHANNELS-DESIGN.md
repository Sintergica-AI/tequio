# Canales de Tequio (módulo `plane.chat`)

Sistema de canales de chat por proyecto y por workspace, estilo ClickUp Chat,
nativo dentro de Tequio (fork de Plane CE v1.4.2). **No confundir con el
producto de chat aparte** (Mattermost rebrandeado para reventa, repos `chat-*`
en Sintergica-AI): esto es una feature interna de Tequio; a mediano plazo
sustituye a Mattermost para uso interno de Sintérgica.

Estado: F1-F4 + v2 desplegadas y verificadas (verify10 32/32, verify11 9/9,
verify12 26/26, E2E WS con cliente Hocuspocus real). Migraciones: chat.0001 y
chat.0002 (ambas generadas dentro de la imagen, dependencia fijada a db.0122).

## Alcance v1

- Canales por proyecto (con `#general` automático) + canales de workspace
- Menciones `@usuario` → `Notification` (entity_name `chat_message`, sin migración upstream)
- Hilos de **un nivel** (estilo Slack: responder a una respuesta cuelga de la raíz)
- Reacciones emoji (código decimal `128077`, patrón `CommentReaction`)
- Vincular work items a mensajes (chips) y crear work item desde un mensaje
- Tiempo real por websocket con **fallback a polling** transparente
- Silenciar canales (F4): `is_muted` por usuario; suprime el badge, no el conteo
- Notificación de mención renderizada (F4): card propio — el NotificationItem
  de fábrica devuelve `<></>` para cualquier notificación sin
  `data.issue_activity.field`, así que sin el branch `entity_name ===
  "chat_message"` las menciones de chat se crean pero JAMÁS se ven
- Badges en vivo (F4): documento workspace-wide `chat:workspace:<workspace_id>`
  — Django emite `channel.activity` (ligero, sin cuerpo) en cada mensaje raíz;
  el live lo autoriza con la sonda barata `GET /chat/me/` (membresía de
  workspace, no de canal). El punto del sidebar usa el único polling fuera del
  chat: unreads cada 60 s vía `useChatUnreadIndicator`

## v2 (misma ronda, 30 Ago 2026)

- **DMs** (1:1 y grupales hasta 9): `is_direct` + `dm_key` (sha256 de los ids
  ordenados, único por workspace) — reabrir con la misma gente devuelve el
  mismo canal. Sin nombre; el cliente pinta los nombres de los demás. Roster
  inmutable, sin PATCH/DELETE del canal.
- **Canales privados**: `access=1`; las filas de `ChannelMember` pasan a ser
  LA autorización (en públicos siguen siendo solo estado). `channel_queryset`
  ahora une públicos-visibles + member_of, con `distinct()` — y por ese join
  los `Count` de mensajes llevan `distinct=True` o se multiplican por
  miembro. Roster: GET/POST/DELETE `channels/<id>/members/`; cualquier
  miembro invita; salir = borrarse a sí mismo. Las menciones a no-miembros de
  un privado NO notifican (no filtrar sería filtrar la conversación).
- **Pins**: `pinned_at`/`pinned_by` en el mensaje; POST/DELETE `…/pin/`,
  GET `channels/<id>/pins/`; difunde `message.updated`.
- **Búsqueda**: GET `/chat/search/?q=` (icontains sobre `message_stripped`,
  máx 50, siempre a través de `channel_queryset` — la privacidad de búsqueda
  se verifica en verify12).
- **Adjuntos**: flujo presign del drive con `entity_type="CHAT"` y
  `attributes.channel_id`; el editor sube vía `uploadFile` del composer y el
  asset id viaja DENTRO del `message_html` (image-component). El GET genérico
  `/api/assets/v2/workspaces/<slug>/<id>/` los sirve (solo valida workspace +
  proyecto — los privados quedan protegidos por UUID + membresía de
  workspace, mismo compromiso que Slack). Límite 25MB.
- **Presencia**: `onlineUsers` del awareness en el header de la sala (punto
  verde + tooltip).
- **Línea "mensajes nuevos"**: `lastSeenAt` se captura ANTES de `markRead`
  (GET membership en `fetchInitialMessages`) y ancla el divisor + botón de
  salto.
- **Gestión de canal en UI**: modal de ajustes (renombrar/descripción/
  archivar/eliminar con confirmación); #general protegido (server y UI).

## Ronda 3 (31 Ago 2026)

- **Salto al mensaje desde búsqueda**: `?anchor=<message_id>` en el GET de
  mensajes devuelve la ventana de 50 raíces que TERMINA en el ancla (un reply
  ancla en su raíz y el cliente abre el hilo encima). El cliente entra en
  "modo historial": banner fijo "Estás viendo mensajes antiguos → Volver a lo
  último", sin anclaje al fondo, resaltado del mensaje 4 s. La paginación
  sigue siendo solo hacia arriba a propósito — volver al presente recarga la
  última página en vez de paginar hacia abajo (compromiso deliberado).
- **Notificaciones de escritorio** (Notification API, campana en la lista
  para pedir permiso): el canal ACTIVO notifica con cuerpo (su conexión trae
  el mensaje completo); el resto vía el doc de workspace SIN cuerpo, con
  estas reglas: DM → siempre; público → solo si `mention_ids` (que el backend
  incluye SOLO en canales públicos — en privados/DMs filtraría a quién se
  menciona a todo el workspace) te incluye; privado (miembro) → siempre;
  silenciado → nunca. Clic → foco + navegar al canal.
- **Pantalla de error/mantenimiento**: ilustración propia con logo Tequio
  (`app/assets/instance/maintenance-mode.png`, transparente, única para ambos
  temas) en `app/error/prod.tsx` y `instance/maintenance-view.tsx`; textos del
  error de producción traducidos al español.
- Fuera de esta ronda: GIFs/link previews, paginación bidireccional,
  limpieza periódica de assets huérfanos (is_uploaded=false).

## Ronda 5 (31 Ago 2026)

- **Enlaces a mensajes**: "Copiar enlace" en el menú del mensaje →
  `…/channels/<id>?message=<mid>`; el deep-link (y el card de notificación de
  mención, que ahora lo incluye) aterriza con jumpToMessage en el mensaje
  exacto.
- **Paginación bidireccional en modo historial**: `?after=<cursor>` devuelve
  las 50 raíces siguientes hacia el presente; al agotar (`has_more: false`) el
  cliente sale solo del modo historial — caminar página a página no puede
  dejar huecos.
- **Menú de canal ampliado**: "Marcar como leído" (si hay no-leídos) y "Salir
  del canal" (privados, no #general).
- **Limpieza oportunista de adjuntos huérfanos**: al presignar, se barren los
  CHAT del propio usuario con is_uploaded=false y >24h — sin beat schedule.

## Ronda 6 (31 Ago 2026) — previsualización de enlaces

- **Backend** `chat/link_preview.py`: `GET /chat/link-preview/?url=` devuelve
  la tarjeta og (title/description/image/site_name/domain) o 204 si no hay
  nada que mostrar. El fetch es del lado del servidor (el navegador muere por
  CORS) y se cachea en el cache de Django: 24 h el acierto, 1 h el fallo —
  una URL se resuelve UNA vez por workspace.
- **SSRF**: buscar URLs arbitrarias desde dentro de la red del compose es el
  caso de libro. Guardas: solo http(s), sin credenciales en la URL, el host
  debe resolver EXCLUSIVAMENTE a direcciones globales (`ip.is_global` sobre
  todos los registros — un solo registro privado rechaza la URL, que es lo
  que explota el DNS rebinding), redirecciones seguidas A MANO (máx 3, cada
  salto revalidado), timeout 3+4 s, solo `text/html`, cuerpo cap a 512 KB
  leído en streaming. La imagen de la tarjeta se limita a http(s) para que no
  cuele `javascript:`/`data:` en un `<img>`.
- **Parser**: `html.parser` de la stdlib (sin BeautifulSoup en la imagen);
  og:* / twitter:* / `<title>`, primera aparición gana, se deja de alimentar
  al llegar a `<body>`.
- **Frontend** `chat/link-preview.tsx`: tarjeta bajo el mensaje con el PRIMER
  enlace externo (mismo origen nunca — esos ya son chips o deep-links, y
  varios enlaces apilando varias tarjetas entierran la conversación).
  `useSWRImmutable` (el backend ya cachea; refetch al enfocar no aporta).
  Verificado en prod: 6/6 (auth, esquema, loopback y red privada rechazados,
  tarjeta real de github.com, caché de 4 ms).
- Sigue fuera: GIFs (pide API externa con clave).

## Ronda 7 (31 Ago 2026) — mensajes que son solo un adjunto

- **BUG que afectaba a los dos clientes**: `if not strip_tags(message_html).strip()`
  rechazaba como "vacío" cualquier mensaje cuyo único contenido fuera una
  imagen — el nodo `<image-component>` no deja texto tras `strip_tags`. O sea
  que enviar SOLO una foto devolvía 400. En la web nunca se notó porque el
  composer siempre mandaba texto; lo cazó la sesión del móvil al subir la
  primera imagen real. Ahora la comprobación es `_has_content()`: texto O un
  nodo de medios (image-component, img, video, file-component). Aplica al
  envío Y a la edición, que tenía el mismo fallo igual de inadvertido.
  Verificado en producción 7/7, incluidos los casos que DEBEN seguir vacíos.
- **Contrato de adjuntos entre clientes** (acordado con la sesión del móvil,
  que no usa el editor): el asset id viaja DENTRO del `message_html` como
  `<image-component src="<asset_id>" id="<asset_id>" status="uploaded">`, NO
  como URL. `src` es el id; cada cliente lo resuelve con
  `/api/assets/v2/workspaces/<slug>/<asset_id>/` (o `.../projects/<pid>/...`
  si el canal tiene proyecto). Ojo: al serializar a HTML los atributos van en
  minúscula (`aspectratio`), y sin `status="uploaded"` la web lo trata como
  subida en curso.
- Aunque el backend ya acepta el adjunto solo, conviene seguir poniendo un pie
  de texto: sin él, el snippet de búsqueda y el cuerpo de la notificación
  salen vacíos.

## Ronda 4 (31 Ago 2026) — UI inspirada en ClickUp + fix crítico

- **FIX CRÍTICO (migración chat.0003)**: todos los DMs tienen `name=""` y
  project NULL, así que el SEGUNDO DM del workspace violaba
  `chat_channel_workspace_name_uq` (Lower("")==""). Pegó en producción en
  cuanto existió un DM real: el verify12 pasó limpio la primera vez (era el
  primer DM) y falló después. La condición del constraint ahora excluye
  `is_direct`. Lección: un constraint condicional que convive con filas
  "vacías por diseño" necesita esa exclusión desde el día uno; y un
  `replace()` de Python sin `assert` falla en silencio — dos imports se
  perdieron así en esta misma ronda.
- Sidebar estilo ClickUp: avatar real en las filas de DM, sufijo con el
  nombre del proyecto en canales de proyecto (vista workspace), botón
  "Mensajes no leídos" que salta al primer canal pendiente, filas de acción
  "+ Mensaje nuevo" y "+ Agregar canal" al final de cada sección.
- Header: stack de avatares del roster (privados/DMs, máx 3 + contador) que
  abre el modal de miembros; el contador verde de conectados se mantiene.
- Empty state del canal: "Chat en #<canal>" + descripción + botón "Agregar
  personas" en privados.
- Composer con placeholder personalizado: "Escribe en #<canal>" / "Escribe a
  <personas>".

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
`database.ts` (fetch = gate de autorización y devuelve `null` — un
`Uint8Array(0)` NO es un update Yjs válido: lib0 lanza "Unexpected end of
array" y el cliente cae con un permission-denied engañoso; store = no-op),
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
