# Metodología: tres programadores con Claude Code sobre el sistema de plugins

Acompaña a [`PLUGINS-PLAN.md`](PLUGINS-PLAN.md). Aquel dice **qué** se construye; este dice **cómo
trabajan tres personas a la vez sin pisarse**, usando Claude Code.

El objetivo no es que cada quien escriba código más rápido. Es que tres agentes trabajando en
paralelo no produzcan tres versiones incompatibles de la misma cosa. Todo lo de abajo apunta a eso.

---

## 1. La regla que sostiene todo: el contrato existe antes que el código

Las tres partes (backend de Tequio, renderizador, plugin) se comunican por un solo protocolo. Si
cada frente lo interpreta a su manera, la integración de la semana 5 es una reescritura.

Por eso la fase 0 no se salta y no se paraleliza:

1. **`features/PLUGINS-DESIGN.md`** es la especificación normativa. Ante cualquier duda, manda.
2. **`Sintergica-AI/tequio-plugin-sdk`** es el contrato ejecutable: tipos de TypeScript, funciones
   de firma, validador de nodos, y dos programas de mentira.
3. Los tres frentes lo revisan y lo aprueban antes de escribir la primera línea de la fase 1.

### Los dos programas de mentira

Son la pieza que permite trabajar en paralelo de verdad:

| Falso | Lo construye | Lo usa | Para qué |
|---|---|---|---|
| **Plugin falso** (servidor que responde el protocolo con datos inventados) | C | A y B | A prueba su proxy sin esperar al plugin real. B renderiza pantallas antes de que existan |
| **Host falso** (CLI que firma contextos y pide vistas) | C | C | C desarrolla el plugin real sin levantar Tequio entero |

El plugin falso incluye, desde el primer día, una pantalla con cada tipo de nodo. Es a la vez
fixture de pruebas y documentación viva.

### Cómo se cambia el contrato

Nunca en silencio, nunca en una rama propia.

1. Quien necesita el cambio abre un PR **solo a `PLUGINS-DESIGN.md` y al SDK**.
2. Lo anuncia a los otros dos y **espera acuse explícito de ambos**.
3. Al mezclarlo, sube la versión del SDK y actualiza el plugin falso.

Un "creo que ya nadie lo está tocando" no es un acuse. Este repo ya tuvo una casi colisión por eso
en agosto: una sesión declaró que no tocaría más el repositorio y otra tenía trabajo en vuelo
minutos después.

---

## 2. Fronteras: un dueño por carpeta

| Frente | Escribe en | No toca |
|---|---|---|
| **A** · Backend y kit | `features/backend/`, `features/verify/`, `build/`, `deploy/` | `plane-src/`, `Comercio exterior/` |
| **B** · Renderizador y frontends | `plane-src/` entero, `features/scripts/regen-patch.sh` | `features/backend/`, `Comercio exterior/` |
| **C** · Plugin y SDK | `Comercio exterior/`, `tequio-plugin-sdk/` | `plane-ce-api-extension/`, `plane-src/` |

Zonas compartidas, que exigen aviso previo:

- `features/PLUGINS-DESIGN.md` y el SDK: cambio por PR con acuse de los otros dos.
- `features/scripts/*.sh`: los toca quien despliega, y avisa. B añade el paquete nuevo a las
  listas de rutas; A añade `plugins` a los bucles de apps.
- `build/backend/Dockerfile`: A es el dueño, pero B debe saberlo si toca aserciones.

Si un frente necesita un cambio en la zona de otro, lo pide. No lo hace "de paso".

---

## 3. Claude Code: cómo se usa en este proyecto

### 3.1 `CLAUDE.md` por repositorio

Es lo primero que lee el agente en cada sesión, así que es donde vive el conocimiento que no se
deduce del código.

- **`Comercio exterior/CLAUDE.md`** ya existe, con siete reglas duras y sus convenciones, más
  reglas por ruta en `.claude/rules/` (núcleo, dominio, datos, portal). **Se respetan tal cual.**
  Cuando la fase 3 cambie la identidad, hay que actualizar `.claude/rules/nucleo.md`: la tabla de
  costuras dice "identidad: propia, mañana Control", y a partir de ahí Control es Tequio.
- **`plane-ce-api-extension/CLAUDE.md`** no existe. Se crea en la fase 0. Contenido mínimo:
  - Las tres capas del repo y qué hay en cada una.
  - Las trampas ya pagadas: los `patch()` de cadena exacta que abortan el build; las migraciones
    que hay que **generar dentro de la imagen** y fijar a `db.0122`; el panel admin que no usa
    i18n; los tokens de diseño `custom-*` que ya no existen en v1.4.2; la interpolación de i18n
    con **una** llave, no dos.
  - Las reglas de coordinación de la sección 6 de este documento.
- **`tequio-plugin-sdk/CLAUDE.md`**: una sola regla grande, la de la sección 7.

### 3.2 Toda tarea arranca en modo plan

Sin excepción para cualquier cosa que toque más de un archivo:

```
/plan Lee features/PLUGINS-PLAN.md y features/PLUGINS-DESIGN.md.
Voy a implementar <la pieza>. Explora el código existente, dime qué vas a
cambiar archivo por archivo y qué patrón existente vas a reutilizar.
```

El plan se lee antes de aprobarlo. Un plan que no cita archivos reales es un plan que se inventó
el código, y aprobarlo cuesta más caro que rehacerlo.

### 3.3 Una rama o un árbol de trabajo por tarea

```bash
git worktree add ../tequio-plugins-backend plugins/a-catalogo
```

Nombres: `plugins/<frente>-<tema>`, por ejemplo `plugins/a-catalogo`, `plugins/b-renderer-tabla`,
`plugins/c-vista-expediente`.

Los árboles de trabajo separados importan aquí más de lo normal: `plane-src` está en HEAD
desacoplado sobre la etiqueta v1.4.2 con el frontend aplicado en el árbol de trabajo y sin
commitear. Dos agentes editándolo a la vez producen exactamente el desastre que ya ocurrió en
agosto con la app móvil, cuando dos sesiones tocaron los mismos archivos y aparecieron funciones
duplicadas.

### 3.4 Qué pedirle y qué no

**Sí:**

- Que cite rutas y líneas reales de lo que afirma. "Esto ya existe en tal archivo" sin ruta es una
  invención hasta que se demuestre lo contrario.
- Que ejecute las pruebas y pegue la salida, no que diga que deberían pasar.
- Que use `/code-review` sobre su propio diff antes de pedir revisión humana.
- Que trabaje contra los falsos del SDK y no contra suposiciones sobre lo que hará el otro frente.

**No:**

- Que decida el contrato. Si el DESIGN no dice algo, la respuesta no es que el agente elija: es
  abrir el PR de la sección 1.
- Que "arregle de paso" algo fuera de su frontera.
- Que dé por bueno un despliegue leyendo su propio registro. Ver la sección 5.

---

## 4. Cierre de una tarea: la lista

Ninguna tarea se da por terminada sin esto. Va literal en el `CLAUDE.md` de cada repo.

**Todos los frentes**

- [ ] `pnpm typecheck` y `pnpm lint` limpios (o `python -m compileall` en el backend).
- [ ] Pruebas nuevas incluidas y en verde.
- [ ] `/code-review` pasado y sus hallazgos atendidos o justificados.
- [ ] Si apareció una trampa nueva, queda anotada en el `CLAUDE.md` que corresponda **con la
      muestra real**, no con una paráfrasis. Una nota inexacta se lee igual de autorizada que un
      dato, y ya bloqueó una ronda entera de trabajo en este proyecto por escribir mal una
      etiqueta.

**Frente A**

- [ ] La migración se generó **dentro de la imagen** con `makemigrations`, no a mano, y su
      dependencia apunta a `db.0122_...` (el generador propone una `0123` que no existe como
      archivo: es la divergencia deliberada del parche de idioma).
- [ ] Cada `patch()` nuevo tiene su aserción, y el ancla es única en el archivo. Hay cadenas que
      aparecen varias veces y el reemplazo cae en la primera.
- [ ] El Dockerfile comprueba el **resultado**, no que el script corriera.
- [ ] `verify14.py` cubre el caso nuevo.

**Frente B**

- [ ] Las claves de i18n están en los **19** locales, con interpolación de una llave.
- [ ] `pnpm --filter @plane/i18n generate:types` ejecutado.
- [ ] `packages/plugin-renderer` sigue presente en `regen-patch.sh` (`PATHS` y `MIN_DIRS`),
      `sync-web.sh`, `sync-space.sh` y `REQUIRED_PATHS` de `prepare-upstream.sh`.
- [ ] `regen-patch.sh` ejecutado y sus aserciones en verde. El parche sano ronda los 550 archivos.
- [ ] Verificado en claro y en oscuro, en `web` **y** en `space`.

**Frente C**

- [ ] Ninguna dependencia nueva con licencia AGPL o GPL (regla ya vigente en su `CLAUDE.md`).
- [ ] Ninguna importación de nada de Plane, ni directa ni transitiva.
- [ ] La vista o acción valida contra el esquema de nodos del SDK.
- [ ] La operación emite auditoría con el formato congelado de `.claude/rules/nucleo.md`.

---

## 5. Verificar es medir lo que crees que mides

Este proyecto ya perdió tardes enteras por instrumentos que respondían fielmente a una pregunta
distinta de la que se les hacía. Va aquí porque se repite:

- El código de salida de `comando > log; echo "exit: $?"` mide el `echo`, siempre cero, mientras el
  registro dice 255. La forma correcta es `rc=$?; ...; exit $rc`.
- `grep -c PALABRA script.sh` cuenta también los comentarios. Hay que excluirlos.
- Deducir que un artefacto está al día por la cronología no mide el artefacto. Se mide con `grep`
  **dentro** del tarball o del bundle del contenedor.
- Que exista una fila en la base no significa que la interfaz la muestre. Las notificaciones del
  chat llevan meses creándose y sin aparecer en la bandeja, porque nadie comprobó el listado.

**Corolario operativo:** se verifica el artefacto final (el bundle servido, el contenido del
tarball, la fila en la base, la respuesta HTTP), nunca el proceso que lo produjo ni el relato de lo
que pasó.

---

## 6. Coordinación

Reglas heredadas de este proyecto, todas aprendidas a golpes:

1. **Antes de editar cualquier archivo de `plane-src`**, preguntar si hay un `sync-*.sh` en vuelo y
   esperar respuesta. El script toma la lista de archivos al arrancar y copia durante minutos:
   editar a mitad deja el servidor con archivos nuevos y viejos mezclados, y el build pasa igual.
2. **Antes de commitear o subir en un repo compartido**, anunciarlo y esperar acuse.
3. **Un `sync` que se corta se repite entero.** Nunca se continúa desde donde murió.
4. **Tras un despliegue ajeno, revalidar lo propio en el bundle nuevo.** Un rebuild de otro
   reemplaza la imagen que verificaste.
5. **Tras cualquier despliegue que cambie código, regenerar el tarball AGPL.** Es un paso suelto
   que se pierde con facilidad cuando dos personas despliegan el mismo día, y deja binarios
   servidos cuya fuente no está publicada.

Ritmo:

- **Diaria de diez minutos.** Tres frases por persona: qué cerré, qué toco hoy, qué necesito de
  quién.
- **Integración semanal, viernes.** Los tres frentes contra los falsos, o contra el real si ya
  existe. Si algo no encaja, sale un PR al DESIGN, no un parche local.
- **Demo al cerrar cada fase.** Con Axel. La de la fase 2 es la importante: es la primera vez que
  se ve una pantalla del plugin dentro de Tequio.

---

## 7. La regla de licencia

Es la única que, si se rompe, no se arregla con un commit.

> **En `tequio-plugin-sdk` y en `Comercio exterior` no entra ni una línea de Plane.** Ni código, ni
> tipos, ni componentes, ni dependencias que arrastren `@plane/*`. Ni copiado, ni adaptado.

El plugin es un programa separado que habla por HTTP con JSON. Esa separación es lo que permite que
su código sea privado frente a la AGPL de Tequio. Si el plugin importa algo de Plane, deja de ser
un programa separado y hay que publicarlo entero.

En la práctica:

- El SDK define sus propios tipos, aunque se parezcan a los de Plane.
- El plugin no conoce el vocabulario visual de Tequio: emite nodos abstractos. Que un
  `indicador` se pinte con las tarjetas de Plane es problema del renderizador, que sí es AGPL.
- Si alguna vez conviene compartir un tipo, se copia el texto al SDK bajo MIT y se anota de dónde
  salió. No se importa.

Ante la duda, se pregunta antes de escribir, no después.

---

## 8. Plantillas de arranque

Para pegar en Claude Code al empezar una tarea. Ajustar lo que va entre paréntesis.

### Frente A · Backend

```
Lee features/PLUGINS-PLAN.md (secciones 4 y 5) y features/PLUGINS-DESIGN.md.

Vas a implementar (la pieza) de la app Django plane.plugins.

Contexto que ya está verificado, no lo vuelvas a investigar:
- El patrón de una app propia está en features/backend/chat/ (modelos, permisos,
  vistas sobre plane.app.views.base.BaseAPIView, urls planas sin prefijo /api/).
- El registro va en features/backend/patch_ce_features.py con patch() de cadena
  exacta que aborta el build si el ancla no está.
- Las migraciones se generan dentro de la imagen y se fijan a db.0122.
- Las llamadas salientes al plugin usan pinned_fetch de
  apps/api/plane/utils/url_security.py.

Primero explora y hazme un plan archivo por archivo. No escribas código todavía.
```

### Frente B · Renderizador y frontends

```
Lee features/PLUGINS-PLAN.md (secciones 4.4 y 5.6) y el esquema de nodos del SDK.

Vas a implementar (los nodos / la ruta / la barra lateral).

Contexto ya verificado:
- Se construye sobre @plane/propel por subrutas, no sobre @plane/ui.
- Las rutas se inyectan en apps/web/app/routes/extended.ts con el trío
  layout/header/page; copia el patrón de (projects)/channels o /finance.
- Los items dinámicos de barra lateral van en
  core/components/workspace/sidebar/sidebar-menu-items.tsx, dentro del
  Disclosure.Panel, entre el map de enlaces fijados y sortedNavigationItems.
  No uses SidebarItemBase: filtra las claves que no conoce.
- i18n: 19 locales, interpolación de una sola llave.

Prueba contra las fixtures del plugin falso del SDK. Plan primero.
```

### Frente C · Plugin

```
Lee CLAUDE.md y .claude/rules/ de este repo, y
features/PLUGINS-PLAN.md del repo tequio (secciones 5 y 6, fase 3).

Vas a convertir (la pantalla / la acción) en una vista del protocolo
tequio-plugin v1.

Reglas que no se negocian:
- Las siete reglas duras de CLAUDE.md siguen vigentes, en especial: nada
  específico de un cliente, el dominio no importa de lib/nucleo/local, los
  estados solo cambian por lib/dominio/estados.ts, y los titulares no son
  usuarios.
- Ni una importación de Plane. El plugin es un programa separado.
- La vista devuelve nodos del vocabulario; valídala contra el esquema del SDK.
- La autorización sigue viviendo en db/repositorio/, no en la vista. La vista
  solo decide qué botones y campos existen.

Pruébalo con el host falso del SDK. Plan primero.
```

---

## 9. Qué mirar para saber si va bien

| Momento | Señal buena | Señal mala |
|---|---|---|
| Fin de fase 0 | Los tres pueden trabajar sin esperarse | Alguien dice "cuando el otro termine, yo…" |
| Semana 2 | El plugin real responde al host falso, y el proxy real al plugin falso | Se sigue discutiendo la forma de un payload |
| Semana 3 | La pantalla `expediente` se ve en Tequio | Solo se han hecho las pantallas fáciles |
| Semana 5 | La integración descubre detalles, no arquitectura | Aparece que hacía falta un tipo de nodo grande |
| Cualquier momento | Los PR son pequeños y se revisan en un rato | Un PR toca los tres frentes |
