# Tequio · imagen de backend (api / worker / beat / migrator).
#
# Apila las DOS capas del repo sobre la imagen oficial de Plane CE, en el mismo
# orden en que se construyeron históricamente en el VPS:
#   1. patch/            → API pública de pages/features + fix del asistente CE
#   2. features/backend/ → wiki, drive, finanzas, asistente, chat y correos
# El orden importa: patch_ce_features.py ancla sobre ficheros que patch_ce.py ya
# tocó. Los dos patchers abortan si un ancla no aparece, así que un cambio de
# upstream rompe el BUILD en vez de producir una imagen a medias.
#
# Contexto de build: la RAÍZ del repositorio.
ARG BASE_BACKEND_IMAGE=makeplane/plane-backend:v1.4.2
FROM ${BASE_BACKEND_IMAGE}

# --- Capa 1 · API pública -----------------------------------------------------
COPY patch/page_ext_serializers.py /code/plane/api/serializers/page_ext.py
COPY patch/page_ext_views.py       /code/plane/api/views/page_ext.py
COPY patch/page_ext_urls.py        /code/plane/api/urls/page_ext.py
COPY patch/patch_ce.py             /tmp/patch_ce.py
RUN python /tmp/patch_ce.py && rm /tmp/patch_ce.py

# --- Capa 2 · funciones Tequio ------------------------------------------------
COPY features/backend/workspace_page_serializers.py /code/plane/app/serializers/workspace_page_ext.py
COPY features/backend/workspace_page_views.py       /code/plane/app/views/workspace_page_ext.py
COPY features/backend/workspace_page_urls.py        /code/plane/app/urls/workspace_page_ext.py
COPY features/backend/drive_views.py                /code/plane/app/views/drive_ext.py
COPY features/backend/drive_urls.py                 /code/plane/app/urls/drive_ext.py
COPY features/backend/finance/                      /code/plane/finance/
COPY features/backend/assistant/                    /code/plane/assistant/
COPY features/backend/chat/                         /code/plane/chat/
# Django fusiona directorios de plantillas: solo se pisan las que traemos.
COPY features/backend/emails/                       /code/templates/emails/

# pypdf: extracción de texto de estados de cuenta en PDF (finanzas). La imagen
# base no trae ninguna librería de PDF.
RUN pip install --no-cache-dir "pypdf>=5,<6"

COPY features/backend/patch_ce_features.py /tmp/patch_ce_features.py
RUN python /tmp/patch_ce_features.py && rm /tmp/patch_ce_features.py

# --- Aserciones de la imagen --------------------------------------------------
# Los patchers ya abortan si un ancla falta, pero eso mide que el REEMPLAZO se
# hizo, no que el resultado sea utilizable. Esto mide el artefacto: que las apps
# quedaron registradas, que las rutas se incluyen, que el código compila y que
# las plantillas de correo son las nuestras y no las de fábrica.
RUN set -e; \
    for app in finance assistant chat; do \
      grep -q "\"plane.$app\"" /code/plane/settings/common.py \
        || { echo "FATAL: plane.$app no quedó en INSTALLED_APPS"; exit 1; }; \
      grep -q "plane.$app.urls" /code/plane/urls.py \
        || { echo "FATAL: las rutas de plane.$app no se incluyeron"; exit 1; }; \
    done; \
    grep -q "workspace_page_ext" /code/plane/app/urls/__init__.py \
      || { echo "FATAL: las rutas de la wiki no se registraron"; exit 1; }; \
    grep -q "drive_ext" /code/plane/app/urls/__init__.py \
      || { echo "FATAL: las rutas del drive no se registraron"; exit 1; }; \
    grep -q "page_ext" /code/plane/api/urls/__init__.py \
      || { echo "FATAL: las rutas de la API pública no se registraron"; exit 1; }; \
    grep -q "Tequio" /code/templates/emails/auth/magic_signin.html \
      || { echo "FATAL: las plantillas de correo siguen siendo las de fábrica"; exit 1; }; \
    python -c "import pypdf" \
      || { echo "FATAL: pypdf no quedó instalado"; exit 1; }; \
    python -m compileall -q /code/plane/finance /code/plane/assistant /code/plane/chat \
      /code/plane/app/views/drive_ext.py /code/plane/app/views/workspace_page_ext.py \
      || { echo "FATAL: el código propio no compila"; exit 1; }; \
    echo "OK: imagen de backend verificada"
