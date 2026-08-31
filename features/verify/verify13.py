"""Renderiza TODAS las plantillas de correo como lo hace cada tarea del worker
y afirma lo que importa. Cada caso se prueba dos veces: con `current_site`
(el envío normal) y sin él (los flujos que no lo pasan), porque el isotipo y la
línea del pie dependen de esa variable y una plantilla que se rompiera sin ella
solo fallaría en producción.
"""

import os
import re
import sys

import django
from django.conf import settings

def _ancestro_con(sub, que):
    """Sube desde este archivo hasta encontrar un directorio que contenga `sub`.

    El árbol de trabajo y el repositorio colocan estos scripts en sitios
    distintos (`sintergica-features/` suelto vs `features/scripts/` y
    `features/verify/` dentro de plane-ce-sintergica), así que una ruta relativa
    fija funciona en uno y falla en el otro. Se busca y se AFIRMA el hallazgo:
    mejor un error que diga qué falta que trabajar sobre el árbol equivocado.
    """
    d = os.path.dirname(os.path.abspath(__file__))
    while True:
        if os.path.exists(os.path.join(d, sub)):
            return d
        padre = os.path.dirname(d)
        if padre == d:
            raise SystemExit(f"FATAL: no encuentro {que} ({sub}) desde {__file__}")
        d = padre


BASE = os.path.join(_ancestro_con("backend/emails", "el paquete de features"), "backend")

settings.configure(
    DEBUG=False,
    TEMPLATES=[
        {
            "BACKEND": "django.template.backends.django.DjangoTemplates",
            "DIRS": [BASE],
            "APP_DIRS": False,
            "OPTIONS": {"string_if_invalid": "!!!VARIABLE_INEXISTENTE!!!"},
        }
    ],
)
django.setup()

from django.template.loader import render_to_string  # noqa: E402
from django.utils.html import strip_tags  # noqa: E402


def plain_text(html_content):
    """Copia literal de plane/utils/email.py."""
    html_content = re.sub(r"<style[^>]*>.*?</style>", "", html_content, flags=re.DOTALL | re.IGNORECASE)
    text_content = strip_tags(html_content)
    text_content = re.sub(r"\n\s*\n\s*\n+", "\n\n", text_content)
    return "\n\n" + text_content.lstrip().rstrip() + "\n\n"


SITE = "https://tequio.sintergica.ai"
LOGO = f"{SITE}/favicon/android-chrome-192x192.png"

ACTOR = {"avatar_url": f"{SITE}/media/avatar.png", "first_name": "Axel", "last_name": "Mújica"}
ISSUE_UPDATES_CTX = {
    "data": [
        {
            "actor_detail": ACTOR,
            "activity_time": "10:32 AM",
            "changes": {
                "state": {"old_value": ["Todo"], "new_value": ["In Progress"]},
                "priority": {"old_value": ["low"], "new_value": ["urgent"]},
                "assignees": {"old_value": ["Ana"], "new_value": ["Beto", "Carla", "Dani"]},
                "labels": {"old_value": [], "new_value": ["bug", "urgente"]},
                "target_date": {"old_value": ["2026-09-01"], "new_value": ["2026-09-10"]},
                "link": {"old_value": [], "new_value": ["https://ejemplo.mx/doc"]},
                "blocking": {"old_value": [], "new_value": ["TEQ-2", "TEQ-3", "TEQ-4"]},
                "duplicate": {"old_value": [], "new_value": ["TEQ-9", "TEQ-10", "TEQ-11"]},
                "name": {"old_value": ["Título viejo"], "new_value": ["Título nuevo"]},
            },
        }
    ],
    "summary": "Hubo cambios en el elemento de trabajo por parte de",
    "actors_involved": 2,
    "issue": {"issue_identifier": "TEQ-1", "name": "Arreglar el correo de invitación"},
    "receiver": {"email": "destino@ejemplo.com"},
    "issue_url": f"{SITE}/sintergica/projects/1/issues/1",
    "project_url": f"{SITE}/sintergica/projects/1/issues/",
    "workspace": "sintergica",
    "project": "Tequio",
    "user_preference": f"{SITE}/sintergica/settings/account/notifications/",
    "comments": [{"actor_comments": {"new_value": ["<p>Ya quedó.</p>"]}, "actor_detail": ACTOR}],
    "entity_type": "elemento de trabajo",
}

CASES = [
    ("emails/invitations/workspace_invitation.html", {
        "email": "invitado@ejemplo.com", "first_name": "Axel Mújica",
        "workspace_name": "Sintérgica & Co.",
        "abs_url": f"{SITE}/workspace-invitations/?invitation_id=abc&slug=sintergica&token=xyz",
    }, [f"{SITE}/workspace-invitations/?invitation_id=abc&slug=sintergica&token=xyz", "Aceptar invitación"]),
    ("emails/invitations/project_invitation.html", {
        "email": "invitado@ejemplo.com", "first_name": "Axel Mújica",
        "project_name": "Tequio Móvil",
        "invitation_url": f"{SITE}/project-invitations/?invitation_id=abc",
    }, [f"{SITE}/project-invitations/?invitation_id=abc", "Aceptar invitación"]),
    ("emails/auth/magic_signin.html", {
        "code": "482915", "email": "axel@sintergica.ai",
    }, ["482915", "10 minutos"]),
    ("emails/auth/forgot_password.html", {
        "first_name": "Axel", "email": "axel@sintergica.ai",
        "forgot_password_url": f"{SITE}/accounts/reset-password/?uidb64=x&token=y",
    }, [f"{SITE}/accounts/reset-password/?uidb64=x&token=y", "contraseña"]),
    ("emails/notifications/project_addition.html", {
        "project_name": "Tequio Móvil", "workspace_name": "Sintérgica",
        "email": "invitado@ejemplo.com", "inviter_first_name": "Axel",
        "project_url": f"{SITE}/sintergica/projects/1/issues",
    }, [f"{SITE}/sintergica/projects/1/issues", "Ir al proyecto"]),
    ("emails/notifications/webhook-deactivate.html", {
        "email": "admin@ejemplo.com",
        "message": "Se desactivó el webhook https://hooks.ejemplo.mx/x porque sus envíos fallaron repetidamente.",
        "webhook_url": f"{SITE}/sintergica/settings/webhooks/abc",
    }, ["hooks.ejemplo.mx", "Ver el webhook"]),
    ("emails/notifications/issue-updates.html", ISSUE_UPDATES_CTX,
     ["TEQ-1", "Comentarios", "Cambios", "Responsable:", "Prioridad:", "destino@ejemplo.com"]),
    ("emails/user/email_updated.html", {"email": "nuevo@ejemplo.com"}, ["nuevo@ejemplo.com"]),
    ("emails/user/user_activation.html", {
        "email": "axel@sintergica.ai", "profile_url": f"{SITE}/profile",
    }, [f"{SITE}/profile", "reactiv"]),
    ("emails/user/user_deactivation.html", {
        "email": "axel@sintergica.ai", "login_url": f"{SITE}/login",
    }, [f"{SITE}/login", "desactiv"]),
    ("emails/exports/analytics.html", {}, ["exportación"]),
    ("emails/test_email.html", {}, ["prueba"]),
]

# Con un directorio como argumento, deja ahí las vistas previas renderizadas.
PREVIEW = sys.argv[1] if len(sys.argv) > 1 else None

fallos = []


def check(cond, msg, tpl):
    if not cond:
        fallos.append(f"{tpl}: {msg}")


for tpl, ctx, obligatorios in CASES:
    for con_sitio in (True, False):
        c = dict(ctx)
        if con_sitio:
            c["current_site"] = SITE
        etiqueta = f"{tpl} [{'con' if con_sitio else 'sin'} current_site]"
        try:
            html = render_to_string(tpl, c)
        except Exception as e:  # noqa: BLE001
            fallos.append(f"{etiqueta}: excepción al renderizar: {e!r}")
            continue
        texto = plain_text(html)

        check("!!!VARIABLE_INEXISTENTE!!!" not in html, "usa una variable que el contexto no define", etiqueta)
        check("{{" not in html and "{%" not in html, "quedan etiquetas de plantilla sin resolver", etiqueta)
        for needle in ("Plane", "plane.so", "makeplane", "planepowers", "plane-marketing"):
            check(needle not in html, f"todavía menciona {needle}", etiqueta)
        check("Tequio" in texto, "la marca no aparece en la versión de texto plano", etiqueta)
        # Los & de las URLs viajan escapados como &amp;: se comparan sin escapar.
        html_sin_escapar = html.replace("&amp;", "&")
        for needle in obligatorios:
            check(needle in html_sin_escapar, f"falta el contenido esperado {needle!r}", etiqueta)
        # El isotipo solo debe aparecer cuando hay dominio absoluto; nunca una
        # ruta relativa, que en un correo no resuelve contra nada.
        if tpl != "emails/notifications/issue-updates.html":
            check((LOGO in html) == con_sitio, "el isotipo no sigue a current_site", etiqueta)
        check('src="/favicon' not in html, "el logotipo quedó como ruta relativa", etiqueta)
        check("http://" not in html.replace("http://www.w3.org", ""), "hay un enlace sin cifrar", etiqueta)

        if con_sitio and PREVIEW:
            destino = os.path.join(PREVIEW, tpl.replace("/", "_"))
            os.makedirs(PREVIEW, exist_ok=True)
            with open(destino, "w", encoding="utf-8") as f:
                f.write(html)

print(f"Plantillas probadas: {len(CASES)} x 2 contextos")
if fallos:
    print(f"\n{len(fallos)} FALLOS:")
    for f in fallos:
        print("  -", f)
    sys.exit(1)
print("Todo correcto.")
