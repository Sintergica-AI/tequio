# Sintergica CE extension: tool schemas exposed to the model, plus dispatch.
#
# Schemas are in OpenAI function-calling shape, which is what OpenAI,
# OpenRouter and the OpenAI-compatible endpoints of Anthropic and Gemini all
# accept — so one definition serves every provider in the god-mode selector.

from plane.assistant import actions, tools
from plane.assistant.tools import ToolError
from plane.utils.exception_logger import log_exception

_PROJECT = {
    "type": "string",
    "description": "Nombre o identificador del proyecto (p. ej. 'SIN' o el nombre completo). Omitir para buscar en todos.",
}

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "whoami",
            "description": (
                "Quién es el usuario que pregunta: nombre, rol en el workspace, zona horaria, "
                "fecha de hoy, proyectos a los que pertenece y cuántos work items tiene abiertos "
                "y vencidos. Úsala al principio cuando la pregunta diga 'mis', 'me', 'yo'."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_projects",
            "description": "Lista los proyectos a los que el usuario tiene acceso.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_work_items",
            "description": (
                "Busca work items con filtros combinables. Devuelve como máximo 100; "
                "si sólo necesitas conteos usa work_item_stats en su lugar."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Texto a buscar en título y descripción."},
                    "project": _PROJECT,
                    "assignee": {
                        "type": "string",
                        "description": "'me' para el usuario actual, o el nombre/email de un miembro.",
                    },
                    "unassigned": {"type": "boolean", "description": "Sólo work items sin responsable."},
                    "state": {"type": "string", "description": "Nombre exacto del estado (p. ej. 'In Progress')."},
                    "state_group": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["backlog", "unstarted", "started", "completed", "cancelled"],
                        },
                        "description": "Grupos de estado. Para 'abiertos' usa backlog, unstarted y started.",
                    },
                    "priority": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["urgent", "high", "medium", "low", "none"]},
                    },
                    "label": {"type": "string"},
                    "cycle": {"type": "string", "description": "Nombre del ciclo, o 'current' para el ciclo en curso."},
                    "module": {"type": "string"},
                    "overdue": {
                        "type": "boolean",
                        "description": "Sólo los que ya pasaron su fecha objetivo y no están cerrados.",
                    },
                    "target_date_before": {"type": "string", "description": "Fecha ISO (YYYY-MM-DD)."},
                    "target_date_after": {"type": "string", "description": "Fecha ISO (YYYY-MM-DD)."},
                    "limit": {"type": "integer", "description": "Máximo de resultados (1-100, por defecto 25)."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_work_item",
            "description": (
                "Detalle completo de un work item: descripción, etiquetas, ciclo, módulos, "
                "sub-items, enlaces, relaciones y comentarios recientes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "identifier": {
                        "type": "string",
                        "description": "Identificador legible como 'SIN-123', o el UUID.",
                    }
                },
                "required": ["identifier"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_cycles",
            "description": "Ciclos con fechas, estado (current/upcoming/completed) y avance.",
            "parameters": {"type": "object", "properties": {"project": _PROJECT}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_modules",
            "description": "Módulos con responsable, fechas, estado y avance.",
            "parameters": {"type": "object", "properties": {"project": _PROJECT}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_members",
            "description": "Miembros del workspace, o de un proyecto concreto, con su rol.",
            "parameters": {"type": "object", "properties": {"project": _PROJECT}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "work_item_stats",
            "description": (
                "Conteos agregados de work items. Mucho más barato que listar: úsala para "
                "'cuántos', 'distribución', 'cómo va' y cualquier pregunta de volumen."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "project": _PROJECT,
                    "group_by": {
                        "type": "string",
                        "enum": ["state", "state_group", "priority", "assignee", "project"],
                        "description": "Por defecto 'state'.",
                    },
                    "assignee": {"type": "string", "description": "'me' o nombre/email."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_pages",
            "description": (
                "Busca en la wiki de la organización y en las páginas de proyecto. "
                "Devuelve extractos y el id de cada página; para leerla entera usa get_page."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "project": _PROJECT,
                    "limit": {"type": "integer"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_page",
            "description": (
                "Contenido completo de una página de la wiki o de un proyecto. Úsala cuando "
                "el usuario pregunte por lo que dice un documento, o para resumirlo o "
                "compararlo. Antes localízala con search_pages."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "identifier": {
                        "type": "string",
                        "description": "El id que devolvió search_pages, o el nombre de la página.",
                    }
                },
                "required": ["identifier"],
            },
        },
    },
]

# Sólo se ofrecen a quien tiene el rol correspondiente (ver all_tool_schemas).
FINANCE_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "finance_overview",
            "description": (
                "Panorama financiero del espacio: ingresos y saldo pendiente por moneda, "
                "situación de cada cliente y alertas de vencidos. Empieza por aquí para "
                "'cómo vamos', 'cuánto nos deben' o cualquier pregunta general de dinero."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finance_collections",
            "description": (
                "Cobros abiertos: qué está pendiente y qué ya venció, con días de retraso "
                "y saldo por cobrar. Para 'a quién hay que cobrarle' o 'qué está vencido'."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finance_pnl",
            "description": (
                "Estado mensual: ingresos reales (pagos cobrados) contra gastos capturados, "
                "mes a mes. Para 'cómo cerró el mes', márgenes y comparaciones entre meses."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "months": {"type": "integer", "description": "Cuántos meses hacia atrás (1-12, por defecto 6)."}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finance_forecast",
            "description": (
                "Proyección a seis meses, caja proyectada y meses de runway por moneda, "
                "más las señales automáticas (cobranza vencida, runway bajo, concentración "
                "de clientes, renovaciones próximas, margen negativo)."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

# Cobranza es un subconjunto: ve lo que necesita para perseguir pagos, no el
# panorama completo ni las proyecciones.
COLLECTIONS_TOOL_NAMES = {"finance_collections"}

# Read-only, all of them: phase 1 cannot change anything in the workspace.
HANDLERS = {
    "whoami": tools.whoami,
    "list_projects": tools.list_projects,
    "search_work_items": tools.search_work_items,
    "get_work_item": tools.get_work_item,
    "list_cycles": tools.list_cycles,
    "list_modules": tools.list_modules,
    "list_members": tools.list_members,
    "work_item_stats": tools.work_item_stats,
    "search_pages": tools.search_pages,
    "get_page": tools.get_page,
    # Las de finanzas se despachan como cualquier otra: cada una vuelve a
    # comprobar el rol por su cuenta (ocultar el schema es UX, la comprobación
    # es la frontera de seguridad).
    "finance_overview": tools.finance_overview,
    "finance_collections": tools.finance_collections,
    "finance_pnl": tools.finance_pnl,
    "finance_forecast": tools.finance_forecast,
}

# Las de escritura no se despachan aquí: el loop crea una acción pendiente y
# sólo un clic humano las ejecuta. Ver actions.py.
WRITE_TOOLS = actions.WRITE_TOOL_NAMES


def finance_tool_schemas(finance_role):
    """Nada para quien no tiene rol; el rol de cobranza sólo ve sus cobros."""
    if finance_role == "finance":
        return FINANCE_TOOL_SCHEMAS
    if finance_role == "collections":
        return [s for s in FINANCE_TOOL_SCHEMAS if s["function"]["name"] in COLLECTIONS_TOOL_NAMES]
    return []


def all_tool_schemas(can_write, finance_role=None):
    """Un usuario que no puede escribir en ningún proyecto no ve siquiera las
    herramientas de escritura: así el modelo no propone algo que va a fallar.
    Lo mismo con finanzas, que además NO son visibles para todo el espacio."""
    return (
        TOOL_SCHEMAS
        + (actions.WRITE_TOOL_SCHEMAS if can_write else [])
        + finance_tool_schemas(finance_role)
    )


def preview_action(name, ctx, arguments):
    """Valida una herramienta de escritura y describe lo que haría. No escribe."""
    if not isinstance(arguments, dict):
        return {"error": "Los argumentos deben ser un objeto JSON."}
    try:
        return actions.preview(name, ctx, arguments)
    except ToolError as exc:
        return {"error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        log_exception(exc)
        return {"error": f"No se pudo preparar {name}: {exc.__class__.__name__}"}


def execute_action(name, ctx, arguments):
    """Ejecuta una acción ya confirmada por una persona."""
    if not isinstance(arguments, dict):
        return {"error": "Los argumentos deben ser un objeto JSON."}
    try:
        return actions.execute(name, ctx, arguments)
    except ToolError as exc:
        return {"error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        log_exception(exc)
        return {"error": f"Falló {name}: {exc.__class__.__name__}"}


def dispatch(name, ctx, arguments):
    """Run a tool. Bad arguments come back as a normal result with an 'error'
    key so the model can retry, instead of aborting the whole turn."""
    handler = HANDLERS.get(name)
    if handler is None:
        return {"error": f"Herramienta desconocida: {name}"}
    if not isinstance(arguments, dict):
        return {"error": "Los argumentos deben ser un objeto JSON."}
    try:
        return handler(ctx, **arguments)
    except ToolError as exc:
        return {"error": str(exc)}
    except TypeError as exc:
        return {"error": f"Argumentos inválidos para {name}: {exc}"}
    except Exception as exc:  # noqa: BLE001
        # Una herramienta que revienta no debe tumbar la conversación entera:
        # se registra para poder arreglarla y el modelo recibe un error que
        # puede explicarle al usuario.
        log_exception(exc)
        return {"error": f"La herramienta {name} falló: {exc.__class__.__name__}"}
