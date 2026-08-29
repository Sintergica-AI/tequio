"""Build-time patcher: registers the workspace-wiki and drive URL modules on
the internal app API. Exact-string patches with hard assertions — if upstream
code changed and a pattern no longer matches, the docker build FAILS instead
of silently producing a broken image. Composes with patch_ce.py (which touches
plane/api/*, not plane/app/urls/__init__.py).
"""

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
    *sorted(glob.glob("/code/plane/finance/*.py")),
    *sorted(glob.glob("/code/plane/finance/migrations/*.py")),
):
    py_compile.compile(f, doraise=True)
    print(f"{OK} compiles {f}")

print("ALL FEATURE PATCHES APPLIED")
