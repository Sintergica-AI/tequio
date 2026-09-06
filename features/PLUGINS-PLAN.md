# Plan de trabajo: sistema de plugins de Tequio

**Estado:** propuesta de arquitectura, lista para arrancar.
**Fecha:** 5 de septiembre de 2026.
**Origen:** evalúa y sustituye la propuesta *Documentación de diseño e integración de plugins en Tequio* v1.0 (4 sep 2026).
**Primer plugin:** Gestión documental aduanal, el módulo hoy en `~/Documents/Proyectos GitHub/Comercio exterior`.

---

## 1. Qué se pidió y qué cambió

La propuesta original planteaba una tienda de plugins y un `BridgeContainer` que montara cada
plugin dentro de un **iframe**, con handshake por credencial temporal y webhooks de vuelta.

Axel descartó el iframe. El requisito es distinto y más exigente:

> Los plugins son **extensiones del sistema**, se ven **nativos**, incluyen **consola y portal**,
> y su código es **privado**, con **licencia de uso por cliente**.

Ese requisito, cruzado con la licencia de Tequio, es lo que decide toda la arquitectura de este
documento. La sección 2 explica por qué.

---

## 2. La restricción que manda: AGPL

Tequio es Plane CE v1.4.2 modificado, es decir **AGPL-3.0**, y se sirve por red con oferta de
fuente (`/source/`, ver `features/source-offer/README.md`). La AGPL obliga a publicar el código de
la obra derivada a cualquiera que use el servicio.

Los módulos propios que ya existen (`plane.finance`, `plane.chat`, `plane.assistant`) viven dentro
del proceso Django y dentro del bundle de React. Son obra derivada sin discusión, y por eso viajan
en el tarball AGPL. **Un plugin privado no puede construirse así.**

La separación defendible es la de **programa aparte**:

| Pieza | Dónde vive | Licencia |
|---|---|---|
| Renderizador de UI declarativa | `packages/plugin-renderer`, dentro de Tequio | AGPL (parte de Tequio) |
| App Django `plane.plugins` | dentro de Tequio | AGPL (parte de Tequio) |
| Protocolo + SDK de TypeScript | repo nuevo `Sintergica-AI/tequio-plugin-sdk` | MIT |
| Plugin (Gestión documental) | servicio propio, BD propia, worker propio | **Propietaria de Sintergica** |

El plugin no importa ni una línea de Plane. Habla con Tequio por HTTP con JSON estructurado, que
es el caso que la FAQ de la GPL trata como programas separados. Es el mismo esquema con el que
Grafana (AGPL) permite plugins propietarios apoyándose en un SDK Apache-2.

> **Pendiente para Axel:** que un abogado revise el texto de licencia del SDK y la frontera antes
> de vender el primer plugin. La arquitectura está diseñada para que la respuesta sea sencilla,
> pero la decisión no es técnica.

### 2.1 Licencia de uso por cliente

- Sintergica emite una llave firmada con **Ed25519** cuyo contenido es
  `{plugin, instance_id, cliente, plan, vence}`.
- **La valida el plugin**, no Tequio: la clave pública va embebida en el binario privado. Así la
  comprobación no se puede quitar parcheando código abierto.
- Sin llamada a casa. Gracia de 15 días tras el vencimiento, después el plugin responde una vista
  de "licencia vencida" y deja de servir datos.
- Se ata a `Instance.instance_id` de Tequio: 24 caracteres hexadecimales generados una sola vez por
  `register_instance` (`apps/api/plane/license/management/commands/register_instance.py`), estables
  mientras viva la base de datos.

**Dónde NO guardarla:** en el modelo `Instance`. Su serializador es `fields = "__all__"` y
`GET /api/instances/` es `AllowAny` cacheado dos horas: cualquier visitante anónimo leería la
llave. Se guarda cifrada en `plugins_catalog.license_key` con el Fernet de
`apps/api/plane/license/utils/encryption.py`, y Tequio se la entrega al plugin por servidor a
servidor.

---

## 3. Evaluación de la propuesta original

### 3.1 Lo que se conserva

Tienda de plugins por espacio de trabajo, accesos dinámicos en la barra lateral, estados de carga
`loading / ready / error / unavailable`, el plugin como sistema externo con soberanía de datos,
webhooks del plugin hacia Tequio, y los casos de uso CU-TQ-01 a CU-TQ-04 (reescritos con roles).

### 3.2 Lo que se corrige

| # | Problema | Decisión |
|---|---|---|
| 1 | "El sistema de plugins es universal sin importar el rol". Contradice al propio RNF-02. | Instalar, desinstalar y habilitar: **admin del espacio de trabajo** (`ROLE.ADMIN` = 20). Abrir: rol ≥ `min_role` del plugin, que por defecto es MEMBER (15). Los permisos finos siguen siendo del plugin. |
| 2 | "El plugin queda instalado en la cuenta del usuario" (CU-TQ-02, POST-01). | Instalación **por espacio de trabajo**, que es el inquilino real de Plane. |
| 3 | Tres handshakes incompatibles: `POST /api/plugin/handshake` con HMAC del contexto, `POST /api/plugin/verify-credential` con code, y un diagrama donde el plugin pide el usuario a Tequio. | **Ninguno.** No hay código temporal ni sesión en el plugin: cada petición lleva el contexto firmado. Ver sección 5. |
| 4 | Iframe, `sandbox`, `SameSite=None`, `frame-ancestors`, `postMessage`. | Desaparecen. El navegador nunca carga el origen del plugin salvo para subir y descargar archivos con URL firmada. Con eso se evaporan los problemas de cookies de terceros en Safari, de doble barra lateral y de tema claro dentro de una interfaz oscura. |
| 5 | Los webhooks del plugin hacia Tequio no llevan firma ni idempotencia (solo se firma en el sentido contrario). | HMAC-SHA256 con ventana de 300 s e `event_id` único por instalación. |
| 6 | "Tequio actualiza tableros y proyectos" sin definir qué significa. | El evento se persiste en `plugins_events` y genera **notificación en la bandeja**. Ojo: hoy la bandeja filtra `entity_name="issue"` (`apps/api/plane/app/views/notification/base.py:66`), así que ni siquiera se ven las del chat propio. Hay que parchearlo, y eso arregla el chat de paso. |
| 7 | "Consumir la configuración proporcionada por los servicios externos" sin decir qué servicio. | Catálogo **en la propia instancia**, tabla `plugins_catalog`, administrado desde god-mode. Sin servidor de catálogo remoto en el MVP. |
| 8 | El plugin aparece como "Injoy" en la tienda. | Se llama **Gestión documental aduanal** (`gestion-documental`, desarrollador Sintergica). Injoy es la agencia que lo instala. Regla dura 1 del módulo: nada específico de un cliente en el código. |
| 9 | "La implementación interna de APIs, bases de datos, generación de tokens o lógica backend queda fuera del alcance". | Alguien lo tiene que construir. Está dentro, es la fase 1. |
| 10 | No hay modelo de licencia comercial. | Sección 2.1. |
| 11 | El diagrama de CU-TQ-04 muestra a Tequio pidiendo y reenviando el frontend del plugin, que no es lo que hace un iframe. Y la página 39 termina con una nota personal del redactor. | Corregir el diagrama y quitar la nota antes de circular el documento. |

---

## 4. Arquitectura

```
  Navegador ──HTTPS──▶ apps/web    /:slug/plugins/gestion-documental/*        ─┐
  Navegador ──HTTPS──▶ apps/space  /spaces/plugins/:instalacion/e/:token/*    ─┤ packages/plugin-renderer
                                                                               │        (AGPL)
                            apps/api · plane.plugins
                            catálogo · instalaciones · licencia
                            proxy de UI firmado · eventos · notificaciones
                                        │
                                   JSON firmado
                                        ▼
                            Plugin privado (servicio propio + BD + worker)
                            /tequio/v1/manifest · vistas · acciones · archivos

  Navegador ──HTTPS──▶ Plugin: solo /api/archivos/{carga,descarga} con URL firmada
                       (subida directa y visor de PDF), CORS al origen de Tequio
```

### 4.1 Toda la interfaz pasa por Django

El navegador nunca habla con el plugin para pedir pantallas. `apps/web` y `apps/space` piden a
Django, y Django reenvía al plugin.

Ventajas que compran esto:

- El origen del plugin no necesita ser público ni confiable para el navegador. Puede estar en la
  red interna del compose.
- No hay CORS, ni cookies de terceros, ni CSP de marcos.
- El contexto (quién pregunta, en qué espacio de trabajo, con qué rol) lo pone Django y va
  **firmado**: el plugin no tiene que confiar en nada que venga del navegador.
- La salida hacia el plugin usa `pinned_fetch` de `apps/api/plane/utils/url_security.py`, que
  resuelve el DNS una vez, valida la IP y conecta contra la IP literal manteniendo el SNI. Cierra
  el DNS rebinding, que es el riesgo real de dejar a un administrador escribir una URL arbitraria.

Coste: una salto extra de red por interacción. Se mitiga cacheando el manifiesto y exigiendo al
plugin respuestas por debajo de 300 ms.

### 4.2 Archivos

Django nunca transporta bytes de documentos, igual que ya hace el módulo Drive. El navegador sube
directo al plugin con una URL firmada por él y descarga igual. Eso obliga a dos cosas en el plugin:

- Crear `app/api/archivos/carga/route.ts`. Hoy `urlFirmadaCarga()` existe en
  `lib/nucleo/local/almacenamiento.ts` y apunta a `/api/archivos/carga`, **pero esa ruta no existe
  y la función no tiene ni un llamador**. Es superficie muerta que ahora sí se usa.
- Que las URL firmadas sean **absolutas**. Hoy `urlFirmadaDescarga()` devuelve una ruta relativa,
  que servía cuando la consola y el almacén compartían origen.

Ambos extremos llevan CORS restringido a los orígenes de `apps/web` y `apps/space`, tope de 40 MB
(`TAMANO_MAXIMO_BYTES` en `db/repositorio/documentos.ts:26`) y una lista blanca de tipos MIME, que
hoy no existe: el portal solo pone el atributo `accept`, que es una pista del navegador y nada más.

### 4.3 El portal del titular

Los titulares son terceros sin cuenta. Entran por enlace firmado de alcance único, y esa regla no
se toca (`.claude/rules/portal.md` del plugin, regla dura 5 de su `CLAUDE.md`).

Se sirve desde **`apps/space`**, la aplicación pública de Plane. En CE solo tiene tres rutas
(`apps/space/app/routes.ts`: índice, `:workspaceSlug/:projectId` e `issues/:anchor`), así que
`plugins/:instalacion/e/:token/*` es un hueco limpio, sin choque con nada de upstream ni de la
edición comercial.

Detalles que importan:

- Los endpoints públicos van con `AllowAny` y **throttle propio**. El global es
  `AnonRateThrottle` a 30 por minuto por IP (`apps/api/plane/settings/common.py:140`), y una
  pantalla que carga una vista y sube seis documentos lo agota. Se añade el scope
  `plugin_public` a 120 por minuto.
- Django solo reenvía vistas y acciones cuyo identificador empiece por `portal.`. Un token de
  titular jamás puede pedir `expedientes` ni `configuracion`.
- El contexto firmado que recibe el plugin en este caso lleva `user: null` y `portal: {token}`.
  **La autoridad del token sigue siendo del plugin**, que lo verifica con `verificarEnlace()` en
  cada petición como hace hoy. Django no sabe qué es un enlace válido y no debe saberlo.
- `apps/space` ya envuelve todo en `ThemeProvider`, `TranslationProvider` y `ToastProvider`
  (`apps/space/app/providers.tsx`), así que el renderizador funciona ahí sin trabajo extra.

### 4.4 El renderizador

`packages/plugin-renderer` es un paquete nuevo del monorepo que consumen `apps/web` y `apps/space`.

Se construye sobre **`@plane/propel`** y no sobre `@plane/ui`:

- `propel` se publica por subrutas, está compilado con `platform: "neutral"` y es lo que `space` ya
  ejercita (`icons`, `tooltip`, `button`, `toast`, `emoji-reaction`).
- `@plane/ui` apenas se usa en `space` (siete símbolos) y **no está en las rutas de
  `regen-patch.sh`**, así que un cambio ahí no viajaría al cliente.
- `propel` trae gráficas basadas en Recharts (`@plane/propel/charts/bar-chart`), tabla, diálogo,
  formulario, insignia, tarjeta, colapsable, pestañas y estado vacío. Cubre el vocabulario entero.

Tailwind lo recoge solo: `packages/tailwind-config/index.css` hace `@source "../**/*.{ts,tsx}"`.
Los Dockerfiles de `web` y `space` hacen `turbo prune --scope=<app> --docker`, así que un paquete
nuevo entra sin tocarlos.

> **Trampa que ya mordió tres veces en este repo.** Los scripts del overlay llevan listas de rutas
> escritas a mano, y una lista corta falla en silencio. `packages/plugin-renderer` hay que
> añadirlo a `features/scripts/regen-patch.sh` (`PATHS` y `MIN_DIRS`), a `sync-web.sh`, a
> `sync-space.sh` y a `REQUIRED_PATHS` de `build/prepare-upstream.sh`. Si falta en alguno, el
> paquete no viaja y nadie se entera hasta que la pantalla sale en blanco en producción.

---

## 5. Protocolo `tequio-plugin` v1

Se publica completo en `Sintergica-AI/tequio-plugin-sdk` (MIT). Este documento es su resumen
normativo; ante discrepancia manda el SDK.

### 5.1 Autenticación: contexto firmado por petición

No hay sesiones, ni cookies, ni códigos de un solo uso. Cada petición de Django al plugin lleva:

| Cabecera | Contenido |
|---|---|
| `X-Tequio-Context` | JSON en base64 (ver abajo) |
| `X-Tequio-Timestamp` | segundos unix, se rechaza fuera de ±300 s |
| `X-Tequio-Signature` | `sha256=` + `HMAC_SHA256(secreto, "{timestamp}.{contexto_b64}.{cuerpo_crudo}")` |

```json
{
  "instance_id": "9f1c2ab34de5f6789a0b1c2d",
  "installation_id": "0f4e…",
  "workspace": { "id": "…", "slug": "sintergica", "name": "Sintergica" },
  "user": { "id": "…", "email": "ana@agencia.mx", "display_name": "Ana Pérez",
            "role": 20, "role_name": "admin" },
  "portal": null,
  "locale": "es",
  "theme": "dark",
  "web_base_url": "https://tequio.cliente.com",
  "portal_base_url": "https://tequio.cliente.com/spaces/plugins/0f4e…"
}
```

En el portal, `user` es `null` y `portal` es `{ "token": "…" }`.

El plugin verifica la firma en su `proxy.ts`, mete el contexto en un `AsyncLocalStorage` y desde
ahí `nucleo.identidad.usuarioActual()` lo lee. La costura no cambia de forma: el dominio sigue sin
saber de dónde sale el usuario.

**Alta de personas.** El plugin resuelve `personal` por correo dentro de la agencia vinculada. Si
no existe la fila y `role_name` es `admin`, la crea con rol `administrador` y audita
`personal.crear` con `quienPidio` de tipo externo. Si no es admin, responde "no estás dado de
alta". Los permisos finos siguen saliendo del catálogo de roles del plugin, no del rol de Tequio.

### 5.2 Endpoints del plugin

| Método y ruta | Cuerpo | Respuesta |
|---|---|---|
| `GET /tequio/v1/manifest` | — | manifiesto (5.3) |
| `POST /tequio/v1/vistas/<vistaId>` | `{parametros, consulta}` | vista (5.4) |
| `POST /tequio/v1/acciones/<accionId>` | `{parametros, datos}` | resultado (5.5) |
| `POST /tequio/v1/archivos/firmar-carga` | `{destino, nombre, tipo, tamano}` | `{url, expira}` |
| `POST /tequio/v1/licencia` | `{llave}` | `{estado, vence, cliente}` |

### 5.3 Manifiesto

```json
{
  "protocolo": 1,
  "clave": "gestion-documental",
  "nombre": "Gestión documental aduanal",
  "version": "1.0.0",
  "icono": "folder-check",
  "navegacion": [
    { "id": "tablero",         "etiqueta": "Tablero",        "icono": "layout-dashboard", "vista": "tablero" },
    { "id": "expedientes",     "etiqueta": "Expedientes",    "icono": "folders",          "vista": "expedientes" },
    { "id": "revision",        "etiqueta": "Por revisar",    "icono": "eye",              "vista": "revision" },
    { "id": "vencimientos",    "etiqueta": "Vencimientos",   "icono": "calendar-clock",   "vista": "vencimientos" },
    { "id": "configuracion",   "etiqueta": "Configuración",  "icono": "settings",         "vista": "configuracion",
      "rolMinimo": 20 }
  ],
  "vistaInicial": "tablero",
  "portal": { "vistaInicial": "portal.expediente" },
  "eventos": [
    "gestion_documental.documento.aprobado",
    "gestion_documental.documento.rechazado",
    "gestion_documental.expediente.completo",
    "gestion_documental.vencimiento.escalado",
    "gestion_documental.validacion.requiere_revision"
  ],
  "licencia": { "estado": "valida", "vence": "2027-09-05" }
}
```

Se cachea cinco minutos en el cache de Django, como hace `chat/link_preview.py`.

### 5.4 Vista

```json
{
  "titulo": "Expediente de Comercializadora del Golfo S.A. de C.V.",
  "migas": [
    { "etiqueta": "Expedientes", "vista": "expedientes" },
    { "etiqueta": "Comercializadora del Golfo S.A. de C.V." }
  ],
  "acciones": [ { "etiqueta": "Exportar expediente", "accion": "expediente.exportar",
                  "parametros": { "id": "…" }, "estilo": "secundario" } ],
  "cuerpo": { "tipo": "pila", "hijos": [ … ] },
  "actualizarCada": null
}
```

`actualizarCada` en segundos pide al host que vuelva a cargar la vista sola. Se usa solo donde hay
trabajo en curso (documento en validación).

### 5.5 Acción

```json
{
  "resultado": { "tipo": "navegar", "vista": "expediente", "parametros": { "id": "…" } },
  "avisos": [ { "severidad": "exito", "mensaje": "Subimos el documento. Lo estamos revisando." } ],
  "erroresDeCampo": null
}
```

`resultado.tipo` puede ser:

- `navegar` con `vista`, `parametros` y `consulta`
- `recargar`, que repite la vista actual
- `descargar` con `url` y `nombre`, para el machote Word y la exportación
- `revelar` con `contenido`, para mostrar una credencial sin meterla en la URL

Esto sustituye por completo la convención actual de `redirect('?aviso=…')` y `?listo=…`, que hoy
mete frases completas en español dentro de la URL.

**Dos GET con efectos secundarios pasan a ser acciones POST**, porque un prefetch o un reintento
no debe dispararlos:

- `expedientes/[id]/exportar` audita `expediente.exportar` al renderizar.
- `expedientes/[id]?credencial=X` descifra y audita una credencial durante el render, con
  `prefetch={false}` como única defensa.

### 5.6 Vocabulario de nodos

Veintiséis tipos, derivados de las diecisiete pantallas reales del módulo. No hay nodo de HTML
crudo: el host controla el aspecto entero.

**Estructura:** `pila`, `columnas`, `rejilla`, `tarjeta`, `seccion`, `desplegable`, `pestanas`.

**Texto:** `titulo` (nivel 1-3), `texto` (tono normal, tenue o peligro), `markdown` (subconjunto,
sin HTML).

**Datos:** `indicador` (KPI con etiqueta, valor, detalle y tono), `insignia` (los catorce estados
de documento y expediente, con la paleta del host), `barraProgreso`, `detalle` (pares
etiqueta/valor), `tabla` (columnas, filas de celdas, paginación), `lista`, `cronologia`,
`graficaBarras`.

**Interacción:** `enlace`, `boton`, `formulario`, `buscador`, `codigoCopiable`, `visorDocumento`.

**Estado:** `alerta` (información, aviso, error, éxito), `estadoVacio`.

Campos de formulario: `texto`, `correo`, `contrasena`, `areaTexto`, `selector`, `radios`,
`casillas`, `archivo`, `numero`, `fecha`, `oculto`. Cada uno admite `requerido`, `deshabilitado`,
`ayuda`, `marcador` y valor inicial.

**Versionado.** El manifiesto declara `protocolo: 1`. Un nodo desconocido no rompe la pantalla: el
renderizador pinta un `estadoVacio` que dice que hay que actualizar Tequio, y registra el tipo en
consola. Añadir nodos es compatible hacia atrás; quitarlos o cambiar su forma sube el entero.

### 5.7 Ejemplo completo: tablero

Recorte real de la pantalla `/tablero` del módulo.

```json
{
  "titulo": "Tablero",
  "migas": [ { "etiqueta": "Tablero" } ],
  "acciones": [],
  "cuerpo": {
    "tipo": "pila",
    "separacion": "grande",
    "hijos": [
      { "tipo": "alerta", "severidad": "aviso",
        "mensaje": "Hay 3 documentos esperando revisión automática desde hace más de una hora. Avisa a quien administra el sistema." },

      { "tipo": "rejilla", "columnas": 3, "hijos": [
        { "tipo": "indicador", "etiqueta": "Expedientes en riesgo", "valor": "4",
          "detalle": "de 37 expedientes abiertos", "icono": "triangle-alert", "tono": "peligro" },
        { "tipo": "indicador", "etiqueta": "Documentos por vencer", "valor": "12",
          "detalle": "con aviso a 30, 15 y 5 días", "icono": "calendar-clock", "tono": "aviso" },
        { "tipo": "indicador", "etiqueta": "Esperando revisión", "valor": "7",
          "detalle": "7 titulares activos", "icono": "eye" }
      ]},

      { "tipo": "seccion", "titulo": "Expedientes que atender",
        "descripcion": "Ordenados por urgencia: primero los que tienen documentos vencidos, luego los de menor avance.",
        "hijos": [
          { "tipo": "lista", "vacio": "No hay expedientes en riesgo.", "elementos": [
            { "principal": { "tipo": "enlace", "texto": "Comercializadora del Golfo S.A. de C.V.",
                             "vista": "expediente", "parametros": { "id": "8f2c…" } },
              "secundario": { "tipo": "columnas", "reparto": [3, 1, 1], "hijos": [
                { "tipo": "barraProgreso", "porcentaje": 62, "tono": "aviso" },
                { "tipo": "texto", "texto": "2 vencidos", "tono": "peligro" },
                { "tipo": "insignia", "estado": "en_revision", "etiqueta": "En revisión" }
              ]}}
          ]}
        ]},

      { "tipo": "enlace", "texto": "5 datos por conciliar entre documentos",
        "vista": "inconsistencias" },

      { "tipo": "columnas", "reparto": [2, 1], "hijos": [
        { "tipo": "seccion", "titulo": "Cargas de documentos", "hijos": [
          { "tipo": "graficaBarras", "etiquetaValor": "documentos",
            "vacio": "Aún no hay cargas de documentos.",
            "series": [
              { "etiqueta": "feb", "valor": 12 }, { "etiqueta": "mar", "valor": 31 },
              { "etiqueta": "abr", "valor": 28 }, { "etiqueta": "may", "valor": 44 },
              { "etiqueta": "jun", "valor": 39 }, { "etiqueta": "jul", "valor": 51 },
              { "etiqueta": "ago", "valor": 47 }, { "etiqueta": "sep", "valor": 9 }
            ]}
        ]},
        { "tipo": "seccion", "titulo": "Actividad reciente", "hijos": [
          { "tipo": "cronologia", "eventos": [
            { "marca": "2 sep, 05:47 p.m.", "tono": "exito",
              "texto": "Se generó un documento", "detalle": "Ana Pérez" },
            { "marca": "2 sep, 05:41 p.m.", "tono": "exito",
              "texto": "Se exportó un expediente", "detalle": "Ana Pérez" }
          ]},
          { "tipo": "texto", "tono": "tenue",
            "texto": "Este mes se consumieron 1,284 créditos de análisis." }
        ]}
      ]},

      { "tipo": "seccion", "titulo": "Próximos vencimientos", "hijos": [
        { "tipo": "tabla",
          "vacio": "No hay vencimientos próximos.",
          "columnas": [
            { "clave": "documento", "etiqueta": "Documento" },
            { "clave": "titular",   "etiqueta": "Titular" },
            { "clave": "vence",     "etiqueta": "Vence" },
            { "clave": "estado",    "etiqueta": "Estado" }
          ],
          "filas": [
            [ { "clase": "texto", "texto": "Constancia de situación fiscal" },
              { "clase": "enlace", "texto": "Importadora del Sureste", "vista": "expediente",
                "parametros": { "id": "1a2b…" } },
              { "clase": "texto", "texto": "18 sep 2026" },
              { "clase": "insignia", "estado": "por_vencer", "etiqueta": "Por vencer" } ]
          ]}
      ]}
    ]
  }
}
```

### 5.8 Ejemplo completo: portal del titular

Recorte de `portal.expediente`, la pantalla única de carga.

```json
{
  "titulo": "Expediente documental de Comercializadora del Golfo S.A. de C.V.",
  "migas": [],
  "acciones": [],
  "cuerpo": {
    "tipo": "pila", "separacion": "grande", "hijos": [
      { "tipo": "tarjeta", "hijos": [
        { "tipo": "titulo", "nivel": 1,
          "texto": "Expediente documental de Comercializadora del Golfo S.A. de C.V." },
        { "tipo": "texto", "tono": "tenue",
          "texto": "Puedes hacerlo en varias visitas. Lo que envíes se guarda aunque cierres esta página." },
        { "tipo": "barraProgreso", "porcentaje": 62, "etiqueta": "14 de 22 documentos listos" }
      ]},

      { "tipo": "alerta", "severidad": "exito",
        "mensaje": "Recibimos tu archivo. Lo estamos revisando." },

      { "tipo": "seccion", "titulo": "Documentos corporativos", "hijos": [
        { "tipo": "tarjeta", "hijos": [
          { "tipo": "columnas", "reparto": [4, 1], "hijos": [
            { "tipo": "titulo", "nivel": 3, "texto": "Acta constitutiva" },
            { "tipo": "insignia", "estado": "rechazado", "etiqueta": "Necesita corrección" }
          ]},
          { "tipo": "alerta", "severidad": "error",
            "mensaje": "El domicilio del acta no coincide con el de la constancia de situación fiscal. Envía el acta con la última reforma de domicilio." },
          { "tipo": "formulario",
            "accion": "portal.enviarDocumento",
            "parametros": { "documentoId": "7c3d…" },
            "enviar": "Enviar corregido",
            "campos": [
              { "clase": "archivo", "nombre": "archivo", "etiqueta": "Acta constitutiva",
                "requerido": true, "acepta": ".pdf,application/pdf", "tamanoMaximo": 41943040,
                "ayuda": "Puede pesar hasta 40 MB." }
            ]}
        ]},
        { "tipo": "tarjeta", "hijos": [
          { "tipo": "columnas", "reparto": [4, 1], "hijos": [
            { "tipo": "titulo", "nivel": 3, "texto": "Poder notarial del representante legal" },
            { "tipo": "insignia", "estado": "aprobado", "etiqueta": "Aprobado" }
          ]},
          { "tipo": "visorDocumento", "clase": "pdf", "nombre": "poder-notarial.pdf",
            "peso": "2.4 MB",
            "url": "https://documental.tequio.cliente.com/api/archivos/descarga?clave=…&expira=…&firma=…" }
        ]}
      ]},

      { "tipo": "seccion", "titulo": "Datos de operación", "hijos": [
        { "tipo": "tarjeta", "titulo": "Claves de acceso", "hijos": [
          { "tipo": "texto", "tono": "tenue",
            "texto": "Se guardan cifradas. Nadie de la agencia puede verlas completas." },
          { "tipo": "formulario", "accion": "portal.enviarCredenciales", "enviar": "Guardar",
            "campos": [
              { "clase": "contrasena", "nombre": "credencial_vucem_usuario",
                "etiqueta": "Usuario de VUCEM",
                "ayuda": "Ya la tenemos guardada (termina en ····4821). Escríbela de nuevo solo si quieres reemplazarla." },
              { "clase": "contrasena", "nombre": "credencial_vucem_clave",
                "etiqueta": "Contraseña de VUCEM" },
              { "clase": "contrasena", "nombre": "credencial_efirma_contrasena_llave",
                "etiqueta": "Contraseña de la llave de e.firma" }
            ]}
        ]}
      ]}
    ]
  }
}
```

### 5.9 Webhooks del plugin hacia Tequio

`POST {tequio}/api/plugins/v1/webhooks/<installation_id>/` con la misma firma de 5.1.

```json
{
  "event_id": "b7c1e2…",
  "event_type": "gestion_documental.expediente.completo",
  "occurred_at": "2026-09-05T18:00:00.000Z",
  "title": "Expediente completo: Comercializadora del Golfo S.A. de C.V.",
  "body": "Los 22 documentos del checklist quedaron aprobados.",
  "vista": "expediente",
  "parametros": { "id": "8f2c…" },
  "recipients": ["ana@agencia.mx"],
  "data": { "expediente_id": "8f2c…", "documentos": 22 }
}
```

Reglas: `event_id` es idempotente por instalación (repetición responde 200 con `duplicate`), y ni
`title` ni `body` ni `data` llevan RFC, nombres de personas físicas ni correos de titulares.

Del lado del plugin sale por la costura de auditoría, no desde la ruta de la petición: se encola en
`pendientes` como tarea `emitir_evento_tequio` y el worker la entrega con los reintentos que ya
tiene (1, 5 y 15 minutos). Así un Tequio caído no rompe una aprobación.

El evento `validacion.requiere_revision` **necesita trabajo previo**: `pasarARevision()` en
`db/repositorio/documentos.ts` no emite auditoría hoy. Hay que añadir la acción
`documento.requiere_revision` y declararla en el descriptor.

---

## 6. Fases

### Fase 0 · Contrato, SDK y andamios

Una semana, los tres frentes juntos. Nada de esta fase se puede paralelizar después.

- `features/PLUGINS-DESIGN.md`: la especificación normativa completa (protocolo, firma, throttle,
  licencia, vocabulario de nodos con su esquema de validación).
- Repo nuevo `Sintergica-AI/tequio-plugin-sdk`, MIT, sin ninguna dependencia de Plane:
  tipos de TypeScript del protocolo, `verificarFirma()`, `leerContexto()`, `firmarWebhook()`,
  validador de nodos, y un **plugin falso** servible (tablero con KPIs, tabla paginada, formulario
  con archivo, visor de documento).
- **Host falso**: un CLI en el mismo SDK que firma contextos y pide vistas y acciones a un plugin
  local. Con él, el frente C trabaja sin Tequio.
- `CLAUDE.md` en la raíz de este repo, que hoy no existe, con las trampas conocidas.

**Aceptación:** el plugin falso responde al host falso y el renderizador (aún vacío) tiene fixtures
con las que trabajar. Los tres frentes firman el DESIGN.

### Fase 1 · Backend `plane.plugins`

Frente A. Crear `features/backend/plugins/`:

| Archivo | Contenido |
|---|---|
| `models.py` | `Plugin` → `plugins_catalog` (`key`, `name`, `description`, `developer`, `version`, `icon_url`, `base_url`, `shared_secret` cifrado, `license_key` cifrada, `min_role`, `categories`, `is_active`); `PluginInstallation` → `plugins_installations`; `PluginEvent` → `plugins_events` con unique `(installation, event_id)` |
| `signing.py` | firma y verificación HMAC, ventana de 300 s, `hmac.compare_digest` |
| `client.py` | llamadas al plugin con `pinned_fetch`, timeout de 8 s, errores mapeados a `unavailable` |
| `permissions.py` | decoradores al estilo de `chat/permissions.py`, 404 en vez de 403 vía `installation_queryset` |
| `views.py` | `me`, `catalog`, `installed`, `install`, `installation`, `manifest`, `ui/vistas/<id>`, `ui/acciones/<id>`, `ui/archivos/firmar-carga`, `events` |
| `public_views.py` | espejo público con `AllowAny`, throttle `plugin_public`, solo prefijo `portal.` |
| `instance_views.py` | CRUD del catálogo y licencia, sobre `plane.license.api.views.base.BaseAPIView` |
| `s2s.py` | recepción de webhooks |
| `tasks.py` | `plugin_event_notify_task`, notificaciones `entity_name="plugin_event"` |
| `migrations/0001_initial.py` | **generada dentro de la imagen**, dependencia fijada a `db.0122_…` |

Modificar: `patch_ce_features.py` (anclas de `INSTALLED_APPS` y de `urls.py`, más el parche del
filtro de la bandeja y el scope de throttle), `build/backend/Dockerfile`, `sync-backend.sh`,
`backend-rebuild.sh`, y escribir `features/verify/verify14.py`.

> **Por qué god-mode y no una pantalla del espacio de trabajo.** El catálogo es dato de instancia y
> guarda un secreto. Un admin de un espacio no debe editar lo que ven los demás ni leer el secreto.
> Además la ruta decide la cookie: `apps/api/plane/authentication/middleware/session.py:23` usa la
> cookie de administrador en cuanto la ruta contiene la subcadena `instances`. Por eso el CRUD va
> bajo `/api/instances/plugins/` y la tienda bajo `/api/workspaces/<slug>/plugins/`.

**Aceptación:** `verify14.py` en verde dentro del contenedor, con el plugin falso corriendo al
lado: catálogo y cifrado, instalación 201/409/403 por rol, proxy de vista, firma inválida
rechazada, throttle público, webhook 202 y duplicado, notificación **creada y además listada** por
`/users/notifications/`, y licencia consultada.

### Fase 2 · Renderizador y frontends

Frente B.

- `packages/plugin-renderer/`: `schema.ts`, `registry.tsx`, `renderer.tsx`, `form.tsx`,
  `client.ts` (interfaz `ClienteUI` con dos implementaciones, sesión y portal), `nodes/*.tsx`,
  `tsdown.config.ts`, y pruebas de render por nodo con las fixtures del SDK.
- `apps/web`: rutas en `app/routes/extended.ts`, servicio, store MobX registrado en
  `root.store.ts` (constructor **y** bloque de reset), hook, componentes de tienda y de página,
  items dinámicos de barra lateral, tarjeta de notificación, i18n en los 19 locales más
  `generate:types`.
- `apps/space`: ruta pública, layout sin barra lateral, servicio público.
- `apps/admin`: pantallas de catálogo en god-mode, en español fijo (ese panel no usa i18n).

Puntos exactos ya localizados:

- Items dinámicos: `apps/web/core/components/workspace/sidebar/sidebar-menu-items.tsx`, dentro del
  `Disclosure.Panel`, entre el `map` de los enlaces fijados y `sortedNavigationItems.map`. **No**
  reutilizar `SidebarItemBase`: filtra cualquier clave que no esté en su lista interna.
- Entrada estática "Plugins": `packages/constants/src/workspace.ts`, icono en `sidebar/helper.tsx`
  y la clave añadida al array `staticItems` de `sidebar-item.tsx`. Sin lo tercero no se pinta, que
  es exactamente lo que pasó con finanzas.
- Tarjeta de notificación: rama por `entity_name === "plugin_event"` en
  `workspace-notifications/sidebar/notification-card/item.tsx`, **antes** de la salida temprana por
  `projectId`.

**Aceptación:** el tablero y el portal del plugin falso se ven correctos en claro y oscuro, en
`web` y en `space`; `regen-patch.sh` pasa sus aserciones con el paquete nuevo dentro; el bundle
desplegado contiene las claves i18n nuevas (comprobado con grep dentro del contenedor, no en el
árbol de fuentes).

### Fase 3 · Gestión documental sin interfaz

Frente C. Es la fase más grande: unas 5,300 líneas se reescriben.

Preparación:

- Mover `formatearFecha` de `components/consola/formato.ts` a `lib/dominio/formato.ts`. Es la única
  cosa que ata el worker a la capa de interfaz (`worker/tareas/vigencias.ts:10`) y hay que quitarla
  antes de borrar `components/`.
- Borrar `components/ui/*` y la dependencia `@base-ui/react`: 213 líneas sin un solo importador.

Identidad y licencia:

- `lib/nucleo/identidad.ts` pierde `AccesoPersonal` entero. Se van las tablas `credenciales` y
  `sesiones`, `lib/nucleo/local/{acceso,contrasena}.ts`, `scripts/crear-administrador.ts`, la
  pantalla `/acceso` y `mi-cuenta`. La regla de `.claude/rules/nucleo.md` decía "cuando llegue
  Control se reemplaza `crearAccesoLocal` y se borran las dos tablas": esto es eso.
- `lib/nucleo/local/tequio/`: `contexto.ts` (AsyncLocalStorage), `firma.ts`, `identidad.ts`,
  `licencia.ts` (Ed25519 con `crypto.verify`, gracia de 15 días), `eventos.ts`.
- `db/esquema/vinculos-tequio.ts`: `{agenciaId, installationId único, workspaceId, instanceId}`,
  migración `0008`. La primera instalación válida reclama la única agencia activa; otra
  `installation_id` se rechaza.

Servidor del protocolo, con los Route Handlers de Next que ya trae el runtime:

- `app/tequio/v1/{manifest,vistas/[id],acciones/[id],archivos/firmar-carga,licencia}/route.ts`
- `proxy.ts` en la raíz, que verifica firma y marca de tiempo y rellena el contexto. Next 16
  renombró `middleware.ts` a `proxy.ts`; el nombre viejo compila con aviso de obsolescencia.
- `app/api/archivos/{carga,descarga}/route.ts` con CORS a `TEQUIO_ORIGENES`, 40 MB y lista blanca
  de MIME.

Vistas y acciones, una por pantalla del inventario: `tablero`, `expedientes`, `expediente`,
`exportar`, `titulares`, `titular`, `revision`, `inconsistencias`, `vencimientos`, `buscar`,
`configuracion`, `generacion`, `ayuda`, `portal.expediente`, `portal.enlaceNoValido`. Las diecinueve
acciones actuales menos las cuatro de contraseña y sesión, devolviendo `resultado` en vez de
`redirect`.

**Aceptación:** todas las vistas validan contra el esquema del SDK; las suites de `db/` y `lib/`
siguen en verde sin tocarlas; las e2e reescritas cubren el portal completo, la URL firmada que
devuelve 200 y 403 al quitarle la firma, el checklist por atributos, y que ninguna respuesta de
listado contenga una credencial en claro.

### Fase 4 · Kit de despliegue e integración

Frentes A y C, con B probando.

- `deploy/plugins/gestion-documental.compose.yaml` con `plugin-gd-web`, `plugin-gd-worker` y
  `plugin-gd-db` en la red por defecto, para que Django alcance al plugin por DNS del compose.
- `import /etc/caddy/sites.d/*.caddy` al final del Caddyfile de `build/proxy`, con aserción de
  `caddy validate`, y volumen `proxy/sites.d`. Es el subdominio por el que el navegador sube y baja
  archivos.
- Subcomando `tequio plugin enable|disable|license <nombre>` en `deploy/bin/tequio`: copia el
  compose, genera claves en `tequio.env`, escribe el fragmento de Caddy, hace `docker login` en
  GHCR con el secreto de descarga del cliente, levanta y registra el plugin en el catálogo.
- Integración real en `tequio.sintergica.ai` con una agencia de prueba, `verify14.py` en producción
  y tarball AGPL regenerado. El renderizador va dentro del tarball; el plugin no.

### Fase 5 · Después del MVP

Multi-inquilino en el plugin (parámetro `agenciaId` en las diez funciones de listado sin filtrar,
correo único por agencia en vez de global), refresco automático donde hay trabajo en curso, plugins
con alcance de proyecto, creación de work items desde eventos, renderizador para la app móvil, y
catálogo remoto de Sintergica con licencias en línea.

---

## 7. Estimación

| Fase | Duración | Frentes |
|---|---|---|
| 0 · Contrato y SDK | 1 semana | los tres |
| 1 · Backend | 4 semanas | A |
| 2 · Renderizador y frontends | 4 semanas | B |
| 3 · Plugin sin interfaz | 4 semanas | C |
| 4 · Despliegue e integración | 1 a 2 semanas | A y C |

**Total: 6 a 7 semanas** para tres personas, con las fases 1 a 3 en paralelo.

Con iframe habrían sido unas 4 semanas. La diferencia la pagan la reescritura de 5,300 líneas de
interfaz y el renderizador, y la compran la apariencia nativa, el portal integrado, la ausencia de
problemas de cookies de terceros y una frontera de licencia defendible.

---

## 8. Riesgos

| Riesgo | Mitigación |
|---|---|
| El vocabulario de nodos se queda corto y hay que ampliarlo a mitad del proyecto | Está derivado de las diecisiete pantallas reales, no inventado. La pantalla `expediente`, que es la más rica del módulo, se implementa en la semana 2 como prueba de fuego, no al final |
| Latencia: cada interacción hace navegador → Django → plugin | Manifiesto cacheado, presupuesto de 300 ms por vista, medición desde la primera semana de integración |
| El throttle anónimo de 30 por minuto ahoga el portal | Scope propio `plugin_public` a 120 por minuto, verificado en `verify14.py` |
| El paquete nuevo no viaja porque falta en alguna lista de rutas | Cuatro archivos identificados por nombre en la fase 2, más una aserción en `prepare-upstream.sh` que falla el build si no está |
| Emitir y revocar licencias es un sistema en sí mismo | El MVP usa llaves generadas a mano con un script del SDK. El emisor con panel es fase 5 |
| La frontera de licencia no convence a un abogado | Se decide en la fase 0, antes de escribir el plugin. Si hubiera que cambiarla, lo que cambia es el empaquetado, no la arquitectura |
| La bandeja de notificaciones exige parchear upstream | Aserción en `build/backend/Dockerfile` que falla el build si el parche no se aplicó |

---

## 9. Reparto entre tres programadores

| Frente | Alcance | Repos y carpetas propias |
|---|---|---|
| **A** · Backend y kit | `plane.plugins`, proxy firmado, endpoints públicos, licencias, notificaciones, `verify14.py`, `deploy/`. **Dueño de `PLUGINS-DESIGN.md`** | `features/backend/`, `build/`, `deploy/`, `features/verify/` |
| **B** · Renderizador y frontends | `packages/plugin-renderer`, `apps/web`, `apps/space`, `apps/admin`, i18n, regeneración del parche | `plane-src/` (todo el frontend) |
| **C** · Plugin y SDK | `tequio-plugin-sdk`, conversión sin interfaz, licencia en el plugin, CI de imágenes | `Comercio exterior/`, `tequio-plugin-sdk/` |

Puntos de integración obligatorios:

- **Semana 2:** A contra el plugin falso de C, y C contra el host falso. Ambos sentidos del
  protocolo funcionando sin la contraparte real.
- **Semana 3:** B contra el plugin real. La pantalla `expediente` completa.
- **Semanas 5 y 6:** todo junto en `tequio.sintergica.ai`.

El detalle de cómo trabajan está en [`PLUGINS-METODOLOGIA-EQUIPO.md`](PLUGINS-METODOLOGIA-EQUIPO.md).
