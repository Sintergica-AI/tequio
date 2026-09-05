"""Build-time patcher: registers the workspace-wiki and drive URL modules on
the internal app API. Exact-string patches with hard assertions — if upstream
code changed and a pattern no longer matches, the docker build FAILS instead
of silently producing a broken image. Composes with patch_ce.py (which touches
plane/api/*, not plane/app/urls/__init__.py).
"""

import re
import sys

OK = "\033[92mOK\033[0m"


def patch(path, old, new, must=True):
    with open(path) as f:
        content = f.read()
    if old not in content:
        if must:
            print(f"FATAL: pattern not found in {path}:\n{old[:200]}")
            sys.exit(1)
        print(f"skip (not found): {path}")
        return
    if new == "":
        # `"" in content` es cierto SIEMPRE, así que un reemplazo vacío se daba
        # por aplicado y el parche no hacía nada, sin error ni aviso. Pasó el
        # 5 Sep 2026 al intentar borrar la tarea de telemetría del beat: el
        # build salió verde y la entrada seguía programada en la imagen.
        # Para quitar código, comenta el bloque en vez de vaciarlo.
        print(f"FATAL: reemplazo vacío en {path}. Comenta el bloque en vez de borrarlo.")
        sys.exit(1)
    if new in content:
        print(f"already patched: {path}")
        return
    with open(path, "w") as f:
        f.write(content.replace(old, new, 1))
    print(f"{OK} patched {path}")


# ---------------------------------------------------------------------------
# Register the two new url modules on the internal app API
# ---------------------------------------------------------------------------
patch(
    "/code/plane/app/urls/__init__.py",
    "from .exporter import urlpatterns as exporter_urls",
    "from .exporter import urlpatterns as exporter_urls\n"
    "from .workspace_page_ext import urlpatterns as workspace_page_ext_urls\n"
    "from .drive_ext import urlpatterns as drive_ext_urls",
)
patch(
    "/code/plane/app/urls/__init__.py",
    "    *exporter_urls,\n]",
    "    *exporter_urls,\n    *workspace_page_ext_urls,\n    *drive_ext_urls,\n]",
)

# ---------------------------------------------------------------------------
# Finance module: register the app and mount its URLs
# ---------------------------------------------------------------------------
patch(
    "/code/plane/settings/common.py",
    '    "plane.authentication",\n    # Third-party things',
    '    "plane.authentication",\n    "plane.finance",\n    # Third-party things',
)
patch(
    "/code/plane/urls.py",
    '    path("api/v1/", include("plane.api.urls")),',
    '    path("api/", include("plane.finance.urls")),\n'
    '    path("api/v1/", include("plane.api.urls")),',
)

# ---------------------------------------------------------------------------
# Assistant module: register the app and mount its URLs. Anchored on the
# finance lines because the finance patch above runs first on the same file;
# patch() is idempotent, so a rebuild over an already-patched image is a no-op.
# ---------------------------------------------------------------------------
patch(
    "/code/plane/settings/common.py",
    '    "plane.finance",\n    # Third-party things',
    '    "plane.finance",\n    "plane.assistant",\n    # Third-party things',
)
patch(
    "/code/plane/urls.py",
    '    path("api/", include("plane.finance.urls")),',
    '    path("api/", include("plane.finance.urls")),\n'
    '    path("api/", include("plane.assistant.urls")),',
)


# ---------------------------------------------------------------------------
# Chat module (canales tipo ClickUp): register the app and mount its URLs.
# Anchored on the assistant lines because that patch runs first on the same
# file; patch() is idempotent, so rebuilds over a patched image are no-ops.
# ---------------------------------------------------------------------------
patch(
    "/code/plane/settings/common.py",
    '    "plane.assistant",\n    # Third-party things',
    '    "plane.assistant",\n    "plane.chat",\n    # Third-party things',
)
patch(
    "/code/plane/urls.py",
    '    path("api/", include("plane.assistant.urls")),',
    '    path("api/", include("plane.assistant.urls")),\n'
    '    path("api/", include("plane.chat.urls")),',
)


# ---------------------------------------------------------------------------
# Idioma de perfil por defecto: "es". El frontend arranca en español para
# visitantes sin preferencia (DEFAULT_LANGUAGE en packages/i18n); si el perfil
# naciera en "en", el usuario nuevo veria la interfaz cambiar a ingles tras
# iniciar sesion. Profile.objects.create(user=user) no pasa idioma (adapter/
# base.py), asi que manda este default del modelo. Sin migracion a proposito:
# el default de un CharField vive en Python, no en el esquema; una migracion
# AlterField en plane.db chocaria con las de upstream al actualizar.
# ---------------------------------------------------------------------------
patch(
    "/code/plane/db/models/user.py",
    '    language = models.CharField(max_length=255, default="en")',
    '    language = models.CharField(max_length=255, default="es")',
)

# ---------------------------------------------------------------------------
# Correos: identidad Tequio y textos en español.
#
# Las plantillas HTML se sustituyen enteras por COPY en el Dockerfile (ver
# backend-rebuild.sh). Aquí van solo los textos que viven en Python —el asunto,
# que es lo primero que se lee en la bandeja y decía "Plane", y los mensajes
# redactados en el código— más los `current_site` que las plantillas necesitan
# para pintar el isotipo, que se sirve desde la propia instancia.
#
# Regla de las plantillas: el nombre "Tequio" va como TEXTO, no dentro de la
# imagen, así que la marca se lee aunque el cliente bloquee las imágenes; y
# cuando el contexto no trae `current_site` el isotipo simplemente se omite.
# ---------------------------------------------------------------------------

# --- Invitación a una organización ---
patch(
    "/code/plane/bgtasks/workspace_invitation_task.py",
    'subject = f"{user.first_name or user.display_name or user.email} has invited you to join them in {workspace.name} on Plane"',  # noqa: E501
    'subject = f"{user.first_name or user.display_name or user.email} te invitó a {workspace.name} en Tequio"',  # noqa: E501
)
patch(
    "/code/plane/bgtasks/workspace_invitation_task.py",
    '            "workspace_name": workspace.name,\n            "abs_url": abs_url,\n        }',
    '            "workspace_name": workspace.name,\n            "abs_url": abs_url,\n'
    '            "current_site": current_site,\n        }',
)

# --- Invitación a un proyecto ---
patch(
    "/code/plane/bgtasks/project_invitation_task.py",
    'subject = f"{user.first_name or user.display_name or user.email} invited you to join {project.name} on Plane"',  # noqa: E501
    'subject = f"{user.first_name or user.display_name or user.email} te invitó al proyecto {project.name} en Tequio"',  # noqa: E501
)
# El contexto del proyecto usa `user.first_name` a secas: quien nunca rellenó su
# nombre firmaba la invitación como cadena vacía.
patch(
    "/code/plane/bgtasks/project_invitation_task.py",
    '            "first_name": user.first_name,',
    '            "first_name": user.first_name or user.display_name or user.email,',
)

# --- Alta en un proyecto (el acceso ya está dado) ---
patch(
    "/code/plane/bgtasks/project_add_user_email_task.py",
    'subject = "You have been invited to a Plane project"',
    'subject = "Ya formas parte de un proyecto en Tequio"',
)
patch(
    "/code/plane/bgtasks/project_add_user_email_task.py",
    '            "project_url": project_url,\n        }',
    '            "project_url": project_url,\n            "current_site": current_site,\n        }',
)

# --- Restablecer contraseña ---
patch(
    "/code/plane/bgtasks/forgot_password_task.py",
    'subject = "A new password to your Plane account has been requested"',
    'subject = "Restablece tu contraseña de Tequio"',
)
patch(
    "/code/plane/bgtasks/forgot_password_task.py",
    '            "forgot_password_url": abs_url,\n            "email": email,\n        }',
    '            "forgot_password_url": abs_url,\n            "email": email,\n'
    '            "current_site": current_site,\n        }',
)

# --- Código de un solo uso (inicio de sesión) ---
# La tarea no recibe el dominio de la instancia y no hay request del que sacarlo:
# se toma de settings.WEB_URL, que es de donde sale `base_host` para el resto.
patch(
    "/code/plane/bgtasks/magic_link_code_task.py",
    "from django.core.mail import EmailMultiAlternatives, get_connection",
    "from django.conf import settings\nfrom django.core.mail import EmailMultiAlternatives, get_connection",
)
patch(
    "/code/plane/bgtasks/magic_link_code_task.py",
    'subject = f"Your unique Plane login code is {token}"',
    'subject = f"Tu código de Tequio: {token}"',
)
patch(
    "/code/plane/bgtasks/magic_link_code_task.py",
    'context = {"code": token, "email": email}',
    'context = {"code": token, "email": email, "current_site": settings.WEB_URL}',
)

# --- Cambio de dirección de correo (código + confirmación) ---
patch(
    "/code/plane/bgtasks/user_email_update_task.py",
    "from django.core.mail import EmailMultiAlternatives, get_connection",
    "from django.conf import settings\nfrom django.core.mail import EmailMultiAlternatives, get_connection",
)
patch(
    "/code/plane/bgtasks/user_email_update_task.py",
    'subject = "Verify your new email address"',
    'subject = "Confirma tu correo nuevo en Tequio"',
)
patch(
    "/code/plane/bgtasks/user_email_update_task.py",
    'context = {"code": token, "email": email}',
    'context = {"code": token, "email": email, "current_site": settings.WEB_URL}',
)
patch(
    "/code/plane/bgtasks/user_email_update_task.py",
    'subject = "Plane email address successfully updated"',
    'subject = "Tu correo de Tequio quedó actualizado"',
)
patch(
    "/code/plane/bgtasks/user_email_update_task.py",
    'context = {"email": email}',
    'context = {"email": email, "current_site": settings.WEB_URL}',
)

# --- Cuenta activada / desactivada ---
patch(
    "/code/plane/bgtasks/user_activation_email_task.py",
    'subject = f"{user.first_name or user.display_name or user.email} has been activated on Plane"',  # noqa: E501
    'subject = "Tu cuenta de Tequio se reactivó"',
)
patch(
    "/code/plane/bgtasks/user_activation_email_task.py",
    'context = {"email": str(user.email), "profile_url": current_site + "/profile"}',
    'context = {"email": str(user.email), "profile_url": current_site + "/profile", "current_site": current_site}',  # noqa: E501
)
patch(
    "/code/plane/bgtasks/user_deactivation_email_task.py",
    'subject = f"{user.first_name or user.display_name or user.email} has been deactivated on Plane"',  # noqa: E501
    'subject = "Tu cuenta de Tequio se desactivó"',
)
patch(
    "/code/plane/bgtasks/user_deactivation_email_task.py",
    'context = {"email": str(user.email), "login_url": current_site + "/login"}',
    'context = {"email": str(user.email), "login_url": current_site + "/login", "current_site": current_site}',  # noqa: E501
)

# --- Webhook desactivado ---
patch(
    "/code/plane/bgtasks/webhook_task.py",
    'subject = "Webhook Deactivated"',
    'subject = "Se desactivó un webhook en Tequio"',
)
patch(
    "/code/plane/bgtasks/webhook_task.py",
    'message = f"Webhook {webhook.url} has been deactivated due to failed requests."',
    'message = f"Se desactivó el webhook {webhook.url} porque sus envíos fallaron repetidamente."',
)
patch(
    "/code/plane/bgtasks/webhook_task.py",
    '            "webhook_url": f"{current_site}/{str(webhook.workspace.slug)}/settings/webhooks/{str(webhook.id)}",\n        }',  # noqa: E501
    '            "webhook_url": f"{current_site}/{str(webhook.workspace.slug)}/settings/webhooks/{str(webhook.id)}",\n'  # noqa: E501
    '            "current_site": current_site,\n        }',
)

# --- Exportación de analíticas (el CSV va adjunto) ---
patch(
    "/code/plane/bgtasks/analytic_plot_export.py",
    "from django.core.mail import EmailMultiAlternatives, get_connection",
    "from django.conf import settings\nfrom django.core.mail import EmailMultiAlternatives, get_connection",
)
patch(
    "/code/plane/bgtasks/analytic_plot_export.py",
    'subject = "Your Export is ready"',
    'subject = "Tu exportación de Tequio está lista"',
)
patch(
    "/code/plane/bgtasks/analytic_plot_export.py",
    'render_to_string("emails/exports/analytics.html", {})',
    'render_to_string("emails/exports/analytics.html", {"current_site": settings.WEB_URL})',
)

# --- Resumen de novedades de un elemento de trabajo ---
# Estas dos cadenas se incrustan en la plantilla como texto ya redactado: si se
# quedan en inglés, el correo traducido sigue diciendo "issue".
patch(
    "/code/plane/bgtasks/email_notification_task.py",
    'summary = "Updates were made to the issue by"',
    'summary = "Hubo cambios en el elemento de trabajo por parte de"',
)
patch(
    "/code/plane/bgtasks/email_notification_task.py",
    '"entity_type": "issue",',
    '"entity_type": "elemento de trabajo",',
)

# --- Correos de prueba (manage.py y el botón del panel de administración) ---
patch(
    "/code/plane/db/management/commands/test_email.py",
    'subject = "Test email from Plane"',
    'subject = "Correo de prueba de Tequio"',
)
patch(
    "/code/plane/license/api/views/configuration.py",
    'subject = "Email Notification from Plane"',
    'subject = "Correo de prueba de Tequio"',
)
patch(
    "/code/plane/license/api/views/configuration.py",
    'message = "This is a sample email notification sent from Plane application."',
    'message = "Mensaje de prueba enviado desde esta instancia de Tequio para comprobar la configuración de correo."',  # noqa: E501
)

# ---------------------------------------------------------------------------
# Sanity: las plantillas de correo tienen que ser las nuestras.
#
# Se comprueba el FONDO, no la forma: no que el archivo exista —el de fábrica
# también existe— sino que el que hay lleva la identidad Tequio y ni una
# mención a Plane. Un COPY con la ruta equivocada dejaría las plantillas
# originales en su sitio y los correos saldrían igual, en inglés y con la marca
# ajena, sin que nada fallara.
# ---------------------------------------------------------------------------
PLANTILLAS = {
    "emails/_tequio_base.html": ["{% block content %}"],
    "emails/invitations/workspace_invitation.html": ["{{workspace_name}}", "url=abs_url"],
    "emails/invitations/project_invitation.html": ["{{project_name}}", "url=invitation_url"],
    "emails/auth/magic_signin.html": ["{{code}}"],
    "emails/auth/forgot_password.html": ["url=forgot_password_url"],
    "emails/notifications/project_addition.html": ["url=project_url", "{{inviter_first_name}}"],
    "emails/notifications/webhook-deactivate.html": ["url=webhook_url", "{{message}}"],
    "emails/notifications/issue-updates.html": ["{{entity_type}}", "{{summary}}"],
    "emails/user/email_updated.html": ["{{email}}"],
    "emails/user/user_activation.html": ["url=profile_url"],
    "emails/user/user_deactivation.html": ["url=login_url"],
    "emails/exports/analytics.html": ["Tequio"],
    "emails/test_email.html": ["Tequio"],
}
for nombre, obligatorias in PLANTILLAS.items():
    ruta = f"/code/templates/{nombre}"
    with open(ruta, encoding="utf-8") as f:
        body = f.read()
    for needle in ["Tequio"] + obligatorias:
        if needle not in body:
            print(f"FATAL: {ruta} no contiene {needle!r} — ¿se copió la plantilla correcta?")
            sys.exit(1)
    # El bloque {% comment %} de cabecera SÍ nombra a Plane: es la atribución de
    # autoría que exige la AGPL, y Django la descarta al renderizar. Lo que no
    # puede nombrarla es el correo que llega al buzón.
    renderizada = re.sub(r"{%\s*comment\s*%}.*?{%\s*endcomment\s*%}", "", body, flags=re.DOTALL)
    for prohibido in ("Plane", "plane.so", "makeplane", "planepowers", "plane-marketing"):
        if prohibido in renderizada:
            print(f"FATAL: {ruta} todavía menciona {prohibido!r} fuera del bloque de atribución")
            sys.exit(1)
    print(f"{OK} plantilla Tequio {ruta}")

# Ninguna plantilla de correo puede quedar sin revisar: si upstream añade una,
# saldría en inglés y con la marca de Plane sin que nadie se entere.
import os  # noqa: E402

encontradas = set()
for raiz, _, ficheros in os.walk("/code/templates/emails"):
    for fichero in ficheros:
        if fichero.endswith(".html"):
            encontradas.add(os.path.relpath(os.path.join(raiz, fichero), "/code/templates"))
esperadas = set(PLANTILLAS) | {
    "emails/_tequio_button.html",
    "emails/_tequio_link_fallback.html",
    "emails/_tequio_recipient_note.html",
}
if encontradas != esperadas:
    print("FATAL: el inventario de plantillas de correo no cuadra.")
    print("  sin revisar:", sorted(encontradas - esperadas))
    print("  esperadas y ausentes:", sorted(esperadas - encontradas))
    sys.exit(1)
print(f"{OK} las {len(encontradas)} plantillas de correo están cubiertas")

# ---------------------------------------------------------------------------
# TELEMETRÍA: fuera. Tequio no recopila datos de uso de sus instancias.
#
# De fábrica, cada instancia empuja métricas (usuarios, workspaces, proyectos,
# work items…) a https://telemetry.plane.so cada pocas horas. Se corta en las
# TRES puertas por las que pasa, porque cerrar solo una deja el mecanismo vivo:
#   1. el programador (celery beat) que la despierta,
#   2. la propia tarea, que además se invoca al registrar la instancia,
#   3. el valor por defecto del interruptor, que ya no tiene mando en la interfaz.
# ---------------------------------------------------------------------------
patch(
    "/code/plane/celery.py",
    '    "push-instance-metrics": {\n'
    '        "task": "plane.license.bgtasks.telemetry_metrics.push_instance_metrics",\n'
    "        \"schedule\": schedule(run_every=timedelta(minutes=METRICS_PUSH_INTERVAL_MINUTES)),\n"
    "    },\n",
    "    # Tequio no recopila telemetría: esta tarea empujaba métricas de la\n"
    "    # instancia a telemetry.plane.so. Se deja comentada, y no borrada, para\n"
    "    # que quede constancia de qué se quitó y por qué.\n"
    '    # "push-instance-metrics": {\n'
    '    #     "task": "plane.license.bgtasks.telemetry_metrics.push_instance_metrics",\n'
    "    #     \"schedule\": schedule(run_every=timedelta(minutes=METRICS_PUSH_INTERVAL_MINUTES)),\n"
    "    # },\n",
)
patch(
    "/code/plane/license/bgtasks/telemetry_metrics.py",
    '    logger.debug("Starting push_instance_metrics task")\n'
    "    try:\n"
    "        _collect_and_push_metrics()",
    "    # Tequio no envía telemetría. La tarea se conserva porque\n"
    "    # register_instance la invoca, pero no hace nada.\n"
    "    return\n"
    '    logger.debug("Starting push_instance_metrics task")\n'
    "    try:\n"
    "        _collect_and_push_metrics()",
)
patch(
    "/code/plane/license/models/instance.py",
    "    is_telemetry_enabled = models.BooleanField(default=True)",
    "    # Tequio no recopila telemetría: el interruptor ya no existe en el panel\n"
    "    # y el valor por defecto deja de mentir sobre lo que hace la instancia.\n"
    "    # Sin migración a propósito: el default de un BooleanField vive en Python\n"
    "    # y una AlterField en plane.license chocaría con upstream.\n"
    "    is_telemetry_enabled = models.BooleanField(default=False)",
)
patch(
    "/code/plane/license/api/views/admin.py",
    '        is_telemetry_enabled = request.POST.get("is_telemetry_enabled", True)',
    "        # Si el formulario no manda el campo, no se activa: el alta de la\n"
    "        # instancia ya no ofrece la casilla.\n"
    '        is_telemetry_enabled = request.POST.get("is_telemetry_enabled", False)',
)

# ---------------------------------------------------------------------------
# PROVEEDOR DE IA: Sintergica AI, que habla el protocolo de OpenAI.
#
# CE construye SIEMPRE `OpenAI(api_key=...)` —es decir, api.openai.com— y además
# valida el modelo contra una lista fija por proveedor. Las dos cosas hacen
# imposible apuntar a un servicio compatible: la llamada se va a otro sitio y,
# aunque no lo hiciera, cualquier modelo real del proveedor se rechazaría por no
# estar en la lista. Se resuelve con una sola clave nueva, LLM_BASE_URL: si
# tiene valor, manda ella.
# ---------------------------------------------------------------------------
patch(
    "/code/plane/utils/instance_config_variables/core.py",
    '    {\n'
    '        "key": "LLM_MODEL",\n'
    '        "value": os.environ.get("LLM_MODEL", "gpt-4o-mini"),\n'
    '        "category": "AI",\n'
    '        "is_encrypted": False,\n'
    '    },\n',
    '    {\n'
    '        "key": "LLM_MODEL",\n'
    '        "value": os.environ.get("LLM_MODEL", "lattice/claude-sonnet-5"),\n'
    '        "category": "AI",\n'
    '        "is_encrypted": False,\n'
    '    },\n'
    '    {\n'
    '        # URL base del proveedor compatible con OpenAI. Vacía = api.openai.com.\n'
    '        "key": "LLM_BASE_URL",\n'
    '        "value": os.environ.get("LLM_BASE_URL", "https://lattice.sintergica.ai/v1"),\n'
    '        "category": "AI",\n'
    '        "is_encrypted": False,\n'
    '    },\n',
)
patch(
    "/code/plane/app/views/external/base.py",
    "    provider = SUPPORTED_PROVIDERS.get(provider_key.lower())\n"
    "    if not provider:",
    "    # Con URL base configurada, el catálogo de modelos es del proveedor y no\n"
    "    # de la lista fija de este fichero: validar contra ella rechazaría\n"
    "    # cualquier modelo real suyo.\n"
    "    (base_url,) = get_configuration_value(\n"
    '        [{"key": "LLM_BASE_URL", "default": os.environ.get("LLM_BASE_URL", "")}]\n'
    "    )\n"
    '    if (base_url or "").strip():\n'
    "        if not api_key:\n"
    '            log_exception(ValueError("Missing API key for the configured LLM provider"))\n'
    "            return None, None, None\n"
    "        if not model:\n"
    '            log_exception(ValueError("Missing model for the configured LLM provider"))\n'
    "            return None, None, None\n"
    "        return api_key, model, provider_key\n"
    "\n"
    "    provider = SUPPORTED_PROVIDERS.get(provider_key.lower())\n"
    "    if not provider:",
)
# Ojo al ancla: la capa 1 (patch/patch_ce.py) YA sustituyó aquí el
# `OpenAI(api_key=api_key)` de fábrica por el mapa provider_base_urls. Este
# parche se apila sobre ESE resultado, no sobre el código original de upstream.
patch(
    "/code/plane/app/views/external/base.py",
    "        client = OpenAI(api_key=api_key, base_url=provider_base_urls.get(provider.lower()))",
    "        (llm_base_url,) = get_configuration_value(\n"
    '            [{"key": "LLM_BASE_URL", "default": os.environ.get("LLM_BASE_URL", "")}]\n'
    "        )\n"
    "        client = OpenAI(\n"
    "            api_key=api_key,\n"
    '            base_url=(llm_base_url or "").strip() or provider_base_urls.get(provider.lower()),\n'
    "        )",
)

# ---------------------------------------------------------------------------
# Sanity: compile every file we touched or added
# ---------------------------------------------------------------------------
import glob
import py_compile

for f in (
    "/code/plane/app/urls/__init__.py",
    "/code/plane/app/urls/workspace_page_ext.py",
    "/code/plane/app/urls/drive_ext.py",
    "/code/plane/app/views/workspace_page_ext.py",
    "/code/plane/app/views/drive_ext.py",
    "/code/plane/app/serializers/workspace_page_ext.py",
    "/code/plane/settings/common.py",
    "/code/plane/urls.py",
    "/code/plane/db/models/user.py",
    "/code/plane/celery.py",
    "/code/plane/license/bgtasks/telemetry_metrics.py",
    "/code/plane/license/models/instance.py",
    "/code/plane/license/api/views/admin.py",
    "/code/plane/utils/instance_config_variables/core.py",
    "/code/plane/app/views/external/base.py",
    *sorted(glob.glob("/code/plane/finance/*.py")),
    *sorted(glob.glob("/code/plane/finance/migrations/*.py")),
    *sorted(glob.glob("/code/plane/assistant/*.py")),
    *sorted(glob.glob("/code/plane/assistant/migrations/*.py")),
    *sorted(glob.glob("/code/plane/chat/*.py")),
    *sorted(glob.glob("/code/plane/chat/migrations/*.py")),
):
    py_compile.compile(f, doraise=True)
    print(f"{OK} compiles {f}")

print("ALL FEATURE PATCHES APPLIED")
