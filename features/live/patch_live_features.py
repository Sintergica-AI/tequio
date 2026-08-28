"""Sintergica: patches apps/live so the collaboration server accepts
workspace-level wiki pages (documentType "workspace_page").

Run from the repo root: python3 sintergica-patches/patch_live_features.py <repo_root>
Exact-string patches with hard assertions.
"""

import os
import sys

OK = "\033[92mOK\033[0m"
ROOT = sys.argv[1] if len(sys.argv) > 1 else "."


def patch(path, old, new, must=True):
    path = os.path.join(ROOT, path)
    with open(path) as f:
        content = f.read()
    if old not in content:
        if new in content:
            print(f"already patched: {path}")
            return
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


# 1. Accept the new document type
patch(
    "apps/live/src/types/index.ts",
    'export type TDocumentTypes = "project_page";',
    'export type TDocumentTypes = "project_page" | "workspace_page";',
)

# 2. Route it to the workspace page service
patch(
    "apps/live/src/services/page/handler.ts",
    'import { ProjectPageService } from "./project-page.service";',
    'import { ProjectPageService } from "./project-page.service";\n'
    'import { WorkspacePageService } from "./workspace-page.service";',
)
patch(
    "apps/live/src/services/page/handler.ts",
    "  throw new AppError(`Invalid document type ${documentType} provided.`);",
    '  if (documentType === "workspace_page") {\n'
    "    return new WorkspacePageService({\n"
    "      workspaceSlug: context.workspaceSlug,\n"
    "      cookie: context.cookie,\n"
    "    });\n"
    "  }\n\n"
    "  throw new AppError(`Invalid document type ${documentType} provided.`);",
)

# 3. PDF export: pick the document type from the input scope
patch(
    "apps/live/src/services/pdf-export/pdf-export.service.ts",
    '    getDocumentType: (_input: PdfExportInput): TDocumentTypes => {\n      return "project_page";\n    },',
    '    getDocumentType: (_input: PdfExportInput): TDocumentTypes => {\n      return _input.projectId ? "project_page" : "workspace_page";\n    },',
)

print("ALL LIVE PATCHES APPLIED")
