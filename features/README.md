# Sintergica features: Wiki por organización + Gestor de archivos (Drive)

Paquete listo para desplegar en el Plane self-hosted (plane.sintergica.ai).

## Qué agrega

**Wiki por organización** (`/sintergica/wiki`)
- Entrada "Wiki" en el sidebar del workspace.
- Listado con pestañas Public / Private / Archived, búsqueda, orden y filtros.
- Editor colaborativo completo (el mismo de las páginas de proyecto): tiempo real
  vía servidor live (`documentType: workspace_page`), versiones, lock, acceso
  público/privado, archivar, duplicar, favoritos, imágenes embebidas.
- Backend: endpoints nuevos `/api/workspaces/<slug>/pages/...` sobre `Page.is_global=True`.
  Sin migraciones de BD.

**Gestor de archivos** (`/sintergica/drive` y `/sintergica/projects/<id>/drive`)
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

**Módulo de Finanzas** (`/<slug>/finance` y pestaña Finanzas en cada proyecto)
- Cada proyecto se trata como un cliente: perfil, contrataciones (iguala recurrente
  o pago único), cobros y pagos. Monedas MXN/USD por contrato, totales separados.
- Dashboard con KPIs, alertas de vencidos/próximos (calculadas al leer, sin cron),
  gráfica de ingresos por mes y tabla de clientes con estado.
- Los cobros de iguala se generan solos al consultar (idempotente por
  `(contrato, periodo)`, tope 24 periodos, solo-crear).
- Acceso restringido: admins + allowlist (`FinanceAccess`) gestionada desde la
  pestaña Acceso del dashboard. Quien no está ni ve el menú ni pasa del 403.
- **Primera función con tablas propias**: app Django `plane.finance` con la
  migración `0001_initial` (5 tablas, aditiva pura). `backend-rebuild.sh` ahora
  respalda la BD (`pg_dump`) y corre el servicio `migrator` antes de recrear
  api/worker/beat — sin ese paso quedan colgados en `wait_for_migrations`.

**Finanzas — clientes, fiscal y filtros** *(ronda de agosto 2026)*
- **Pestaña Clientes** con distribución de ingresos por cliente (barra apilada
  por moneda, cada cliente con su color; el color se auto-asigna de una paleta
  y se puede cambiar en el perfil).
- **Datos fiscales por cliente**: razón social, RFC (validado y normalizado),
  régimen, C.P., correo de facturación y la **CSF en PDF** (sube a MinIO con el
  mismo flujo prefirmado del Drive, entity_type `FINANCE_CSF`; se visualiza
  inline y el reemplazo marca la anterior como borrada).
- **Importación de estados de cuenta en PDF**: el backend extrae el texto con
  `pypdf` (la imagen lo instala en el build); un PDF escaneado sin texto da un
  error accionable. CSV y texto pegado siguen funcionando.
- **Análisis del CFO IA guardados**: tabla `finance_analyses`; cada generación
  se persiste con autor, fecha y el periodo filtrado; historial consultable y
  borrable desde la tarjeta de Resumen.
- **Filtro por rango de fechas** (presets + meses libres) en Resumen, Clientes
  y Estados: acota ingresos, gráfica mensual, P&L y gastos vía
  `?date_from&date_to`. Lo pendiente de cobro es siempre "al día de hoy".
- Migración `finance.0003` (aditiva pura): 7 columnas nuevas en
  `finance_profiles` + tabla `finance_analyses`. Verificación: `verify7.py`
  (29 comprobaciones) + E2E real de PDF→IA y análisis guardado.

**Roles financieros por miembro + Cobranza** *(ronda de agosto 2026)*
- El acceso a Finanzas se gestiona en **Configuración → Miembros**: columna
  "Finanzas" por miembro (solo admins) con Sin acceso / Financiero / Cobranza.
  Upsert por miembro (`POST finance/access/ {member_id, role}`; `role:"none"`
  retira). La pestaña "Acceso" del dashboard desapareció.
- **Rol Cobranza**: solo ve `finance/collections/` (cobros pendientes/vencidos
  de todos los clientes, con restante y días) y registra pagos contra ellos.
  Todo lo demás (dashboard, P&L, gastos, análisis, fiscal) responde 403; el
  frontend le muestra únicamente la vista de cobranza, sin pestañas.
  Financiero y admin son supraconjuntos: también ven la pestaña Cobranza.
- Migración `finance.0004` (campo `role` en finance_access, aditiva).
  Verificación: `verify8.py`, 24 comprobaciones en producción.

**Asistente conversacional** (`plane.assistant`) — *fases 1 y 2 completas*
- Chat con contexto real del workspace: responde consultando work items, proyectos,
  ciclos, módulos, miembros y páginas mediante 9 herramientas sobre el ORM.
- Conversaciones persistentes y **privadas de su autor** (sin override de admin),
  con streaming SSE token a token y selector de modelo por conversación.
- Cada herramienta corre con el alcance del usuario que pregunta —los proyectos donde
  es miembro activo—, nunca con una cuenta de servicio. Por eso va contra el ORM y no
  contra el MCP, que autentica con una `X-API-Key` fija, es decir siempre la misma
  identidad.
- Tope de tokens por workspace y mes (`ASSISTANT_MONTHLY_TOKEN_CAP`, 5M por defecto).
- Tercera función con tablas propias: app Django `plane.assistant`, migración
  `assistant.0001_initial` (3 tablas, aditiva pura).
- **Interfaz**: panel acoplado a la derecha en todas las páginas del workspace
  (ancho arrastrable) + página completa en `/<slug>/assistant`. El botón vive en
  la barra superior y sólo aparece si el proveedor está configurado.
- Los `SIN-123` de las respuestas son enlaces al work item. La traza de
  herramientas se ve durante la espera. El selector de modelo cambia de modelo
  sobre la marcha, incluso antes del primer mensaje.
- Diseño completo, decisiones y trampas en [`ASSISTANT-DESIGN.md`](ASSISTANT-DESIGN.md).

### API del asistente

Base: `/api/workspaces/<slug>/assistant/`

| Verbo | Ruta | Notas |
|---|---|---|
| GET | `/config/` | proveedor, modelos permitidos, herramientas, cuota |
| GET POST | `/conversations/` | listar / crear |
| GET PATCH DELETE | `/conversations/<id>/` | sólo el dueño; ajeno → 404 |
| POST | `/conversations/<id>/messages/` | **SSE**: `token`, `tool_call`, `tool_result`, `pending_action`, `awaiting_confirmation`, `done`, `error` |
| POST | `/actions/<id>/` | `{decision:"confirm"\|"reject"}` → SSE; **único punto que escribe** |

**Fase 2: escritura con confirmación humana.** Cuatro herramientas —
`create_work_item`, `update_work_item`, `add_comment`, `add_to_cycle`— que el
modelo **propone** y que sólo se ejecutan al pulsar un botón. El loop nunca las
despacha: valida la propuesta, crea una fila `Action` pendiente y corta el turno.
`POST /actions/<id>/` con `confirm` es el único sitio del código que escribe en
el workspace, y revalida permisos y existencia porque entre la propuesta y el
clic pueden haber cambiado.

Eso no es cortesía de interfaz: los títulos, descripciones y comentarios los
escribe cualquiera del equipo y acaban en el contexto del modelo, así que una
descripción puede intentar dar órdenes. El clic es la frontera.

Detalle que hay que respetar al tocar esto: un turno con `tool_calls` sin su
mensaje `tool` rompe la siguiente petición al proveedor. Por eso al decidir (o
al escribir otro mensaje ignorando el botón) se cierran **todos** los
`tool_calls` sin resolver. Escribir exige rol ≥ 15 en el proyecto; a quien no
puede escribir no se le ofrecen siquiera esas herramientas.

### Tres trampas del streaming (documentadas para no repetirlas)

1. **Un generador síncrono NO se transmite.** Django lo materializa entero con
   `await sync_to_async(list)(...)` antes de emitir nada. El generador es async.
2. **`GZipMiddleware` comprime también el streaming** y zlib retiene los frames
   pequeños. La respuesta declara `Content-Encoding: identity`, que es la vía de
   escape que el propio middleware define.
3. **Un regex con flag `g` a nivel de módulo + función recursiva = cuelgue.**
   `lastIndex` es estado compartido; la llamada anidada rebobina el bucle
   exterior. Un regex por llamada.

## Contenido

```
backend/               → archivos python + patcher (imagen derivada de la actual del api)
backend/assistant/     → app Django del asistente de IA (modelos, herramientas, loop SSE)
                         frontend en plane-src: core/components/assistant/, store, servicio
web-live.patch         → git diff con 58 archivos (frontend web + servidor live + i18n)
remote-deploy.sh       → se ejecuta en el VPS: build de 3 imágenes + actualización del compose
deploy.sh              → sube el paquete por scp y ejecuta remote-deploy.sh
sync-web.sh            → sólo frontend: copia archivos, reconstruye la imagen web y la recrea
sync-admin.sh          → lo mismo para apps/admin (god-mode); sync-web.sh no lo cubre
fix-live-image.sh      → parche puntual del compose para el servicio live
verify*.py             → pruebas funcionales que se ejecutan dentro del contenedor api
                         (verify5.py = asistente, 100 comprobaciones, sin llamar al proveedor)
```

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

**Asistente de IA de CE (el de fábrica).** No es una sección del menú: el botón vive
dentro del editor de descripción del *modal* de un work item, y sólo aparece si
`has_llm_configured` es verdadero y ya escribiste un título. Hay otro en el editor de
Páginas, en el handle `⋮⋮` de cada bloque. Se configura en `/god-mode/ai/`. El panel
de chat lateral que sale en el marketing de Plane es de la edición Commercial y **no
existe en CE** — por eso el módulo de abajo.

**Correo por Resend.** El panel de `/god-mode/email/` tiene un selector de proveedor:
*Resend* pide sólo la API key y la dirección del remitente, y rellena el resto
(`smtp.resend.com`, puerto 587, usuario `resend`, TLS); *SMTP personalizado* deja el
formulario completo de siempre. No hay backend nuevo ni claves de instancia nuevas —
Resend expone SMTP, así que lo que se guarda es una configuración SMTP normal y el modo
se deduce del host. Comprobado que el VPS no bloquea los puertos SMTP de salida, que es
la única razón de peso para haber usado la API HTTP en su lugar.

**Panel admin en español.** `apps/admin` no usa i18n: son cadenas fijas, y están
traducidas directamente (241 reemplazos). `app/root.tsx` lleva `lang="es"` y
`<meta name="google" content="notranslate">`, porque antes Chrome traducía el panel
al vuelo y convertía "Plane" en "avión" ("Redirigir al avión"). Los nombres de campo
de las consolas de Google/GitHub/GitLab ("Authorized Callback URI"…) se dejan en inglés
a propósito: es el literal que hay que buscar allí. Para desplegarlo hay
[`sync-admin.sh`](sync-admin.sh) — `sync-web.sh` sólo mira `apps/web`, así que los
cambios del panel no llegaban nunca a producción.

**`LLM_MODEL` es multi-valor.** El selector de god-mode permite marcar varios modelos y
los guarda separados por comas en una sola clave. Cualquier código que lea esa clave
tiene que partirla; mandarla entera como nombre de modelo es un 404.

## Desplegar

```bash
bash sintergica-features/deploy.sh
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
En `/opt/plane-src`: `git apply -R /opt/sintergica-features/web-live.patch`.
