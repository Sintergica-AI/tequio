# plane-ce-api-extension

Extensión para **Plane Community Edition v1.4.2** que expone *Pages* (wiki) y
*features* en el **API público** (autenticación por `X-API-Key`), y corrige el
asistente de IA integrado.

Con esto el [servidor MCP oficial de Plane](https://github.com/makeplane/plane-mcp-server)
puede gestionar páginas contra una instancia self-hosted de CE, algo que de
fábrica solo funciona contra Plane Cloud / Commercial.

---

## El problema

El servidor MCP oficial y el `plane-sdk` están construidos contra el API de
Plane Cloud. En Community Edition existen **dos APIs distintas**:

| API | Ruta | Autenticación | ¿Incluye pages? |
|---|---|---|---|
| Público | `/api/v1/` | `X-API-Key` | ❌ ruta inexistente → **404** |
| Interno (app web) | `/api/` | Cookie de sesión | ✅ sí, pero rechaza API keys → **401** |

Los módulos registrados en el API público de CE son solo:

```
asset, cycle, intake, label, member, module,
project, state, user, work_item, invite, sticky
```

No hay `page` ni `collection`. Verificado también en la rama `preview`: **no es
cuestión de actualizar**, es una diferencia de edición. Además, el modelo
`APIToken` de CE no tiene ningún campo de *scope*, así que no hay permisos que
ampliar — el alcance lo define qué vistas aceptan `APIKeyAuthentication`.

Resultado: las herramientas `page`, `collection` y `get_features` del MCP
devuelven 404 contra CE.

## La solución

Se añaden rutas al API público que reutilizan el modelo `Page` y las tareas en
segundo plano ya existentes en CE, de modo que las páginas creadas por API se
comportan igual que las creadas desde la interfaz web (incluida la generación
de `description_stripped` vía `page_transaction`).

El esquema de respuesta replica lo que espera el modelo pydantic `Page` del
`plane-sdk`, por lo que **el servidor MCP oficial funciona sin modificarlo**.

### Endpoints añadidos

| Método | Ruta | Notas |
|---|---|---|
| `GET` `POST` | `/api/v1/workspaces/{slug}/pages/` | `?archived=true` para archivadas |
| `GET` `PUT` `PATCH` `DELETE` | `/api/v1/workspaces/{slug}/pages/{id}/` | |
| `POST` `DELETE` | `/api/v1/workspaces/{slug}/pages/{id}/archive/` | archivar / desarchivar |
| `GET` `POST` | `/api/v1/workspaces/{slug}/projects/{pid}/pages/` | |
| `GET` `PUT` `PATCH` `DELETE` | `/api/v1/workspaces/{slug}/projects/{pid}/pages/{id}/` | |
| `POST` `DELETE` | `/api/v1/workspaces/{slug}/projects/{pid}/pages/{id}/archive/` | |
| `GET` `PATCH` | `/api/v1/workspaces/{slug}/projects/{pid}/features/` | mapeado a los flags reales de CE |
| `GET` `PATCH` | `/api/v1/workspaces/{slug}/features/` | features de workspace: solo lectura |
| `GET` … | `/api/v1/workspaces/{slug}/collections/…` | *stub* (ver limitaciones) |
| `GET` … | `…/work-items/{id}/pages/…` | *stub* (ver limitaciones) |

Permisos: se valida membresía activa de proyecto/workspace; solo el propietario
de la página o un admin puede eliminarla; `access` solo lo cambia el propietario.

### Corrección del asistente de IA

CE trae la IA integrada (`/api/workspaces/{slug}/ai-assistant/`) con soporte
declarado para OpenAI, Anthropic y Gemini — pero el código instanciaba
`OpenAI(api_key=...)` **sin `base_url`**, así que todas las peticiones iban a
`api.openai.com` y solo OpenAI podía funcionar.

El parche enruta cada proveedor a su endpoint compatible con OpenAI y actualiza
la lista de modelos de Anthropic, que estaba congelada en la era claude-3.

## Limitaciones (funciones exclusivas de Plane Commercial)

CE **no tiene modelo de datos** para estas funciones, así que se exponen como
*stubs* honestos —listado vacío en lectura y mensaje explicativo en escritura—
en lugar de fallar con 404:

- **Collections** (agrupación de páginas). Alternativa en CE: páginas anidadas
  con `parent_id`.
- **Páginas adjuntas a work items**.
- **Features de workspace** (`initiatives`, `teams`, `customers`,
  `project_grouping`) y de proyecto (`epics`, `workflows`, `parallel_cycles`,
  `project_updates`): se reportan siempre como `false`.

> En CE las páginas viven **dentro de cada proyecto**
> (`/{workspace}/projects/{projectId}/pages/`). El *Wiki* a nivel workspace del
> sidebar es de la versión Commercial.

## Instalación

La imagen se construye **derivando de la oficial** — no recompila el código
fuente y **no requiere migraciones de base de datos**, lo que mantiene el riesgo
al mínimo y permite revertir en un comando.

```bash
git clone git@github.com:Sintergica-AI/plane-ce-api-extension.git
cd plane-ce-api-extension/patch
docker build -t plane-backend-custom:v1.4.2-mcp .
```

En el `docker-compose.yaml` de tu instalación, reemplaza la imagen en los
servicios `api`, `worker`, `beat-worker` y `migrator`:

```yaml
# antes
image: makeplane/plane-backend:${APP_RELEASE:-v1.4.2}
# después
image: plane-backend-custom:v1.4.2-mcp
```

Recrea solo esos servicios (la base de datos no se toca):

```bash
docker compose --env-file=plane.env up -d --no-deps --force-recreate api worker beat-worker
```

### Activar el asistente de IA

Añade a tu `plane.env` y recrea la API:

```env
LLM_PROVIDER=anthropic
LLM_MODEL=claude-sonnet-4-5
LLM_API_KEY=sk-ant-...
```

Proveedores válidos: `anthropic`, `openai`, `gemini`.

## Verificación

```bash
TOKEN=<tu personal access token de Plane>
SLUG=<tu workspace slug>
PID=<uuid de un proyecto>
BASE=https://tu-plane.example.com

curl -s -H "X-API-Key: $TOKEN" \
  "$BASE/api/v1/workspaces/$SLUG/projects/$PID/pages/"

curl -s -H "X-API-Key: $TOKEN" -H "Content-Type: application/json" \
  -X POST -d '{"name":"Prueba","description_html":"<p>Hola</p>"}' \
  "$BASE/api/v1/workspaces/$SLUG/projects/$PID/pages/"
```

Probado end-to-end: ciclo CRUD completo (crear, leer, actualizar, archivar,
desarchivar, eliminar) vía HTTP directo y a través del servidor MCP oficial.

## Cómo funciona el parche

`patch/patch_ce.py` corre durante el build y aplica reemplazos de cadena
**exactos con aserciones**: si una versión futura de Plane cambia el código y un
patrón deja de coincidir, el build **falla** en vez de producir silenciosamente
una imagen rota. Al final compila todos los archivos tocados.

Al actualizar Plane: cambia el tag base en `patch/Dockerfile`, reconstruye y
corrige los patrones que el script reporte como no encontrados.

## Revertir

Restaura la imagen oficial en el `docker-compose.yaml` y recrea los servicios.
No hay cambios de esquema en la base de datos que deshacer.

## Licencia

Este repositorio contiene código derivado de
[Plane](https://github.com/makeplane/plane), licenciado bajo **AGPL-3.0**. Los
archivos de esta extensión se distribuyen bajo la misma licencia. Ver `NOTICE`.
