# Sintergica: plane-backend CE + public-API pages/features/collections + AI fix.
# Derived image: adds files on top of the official image, no source rebuild.
FROM makeplane/plane-backend:v1.4.2

COPY page_ext_serializers.py /code/plane/api/serializers/page_ext.py
COPY page_ext_views.py       /code/plane/api/views/page_ext.py
COPY page_ext_urls.py        /code/plane/api/urls/page_ext.py
COPY patch_ce.py             /tmp/patch_ce.py

RUN python /tmp/patch_ce.py && rm /tmp/patch_ce.py
