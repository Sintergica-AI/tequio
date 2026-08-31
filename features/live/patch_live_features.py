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


# ---------------------------------------------------------------------------
# Chat channels (Tequio canales): documentType "channel".
# The Y.Doc for a channel is intentionally empty — the socket only carries
# stateless JSON events + awareness; Postgres (Django) is the source of truth.
# These patches chain on the strings the workspace_page patches above already
# produced, so order matters.
# ---------------------------------------------------------------------------

# 4. Accept the "channel" document type (chains on patch #1's output)
patch(
    "apps/live/src/types/index.ts",
    'export type TDocumentTypes = "project_page" | "workspace_page";',
    'export type TDocumentTypes = "project_page" | "workspace_page" | "channel";',
)

# 5. Database extension: a channel doc has no binary to fetch or store.
#    fetch doubles as the authorization gate — pages get resource-level auth
#    for free when Django rejects the binary fetch; channels need it explicit.
patch(
    "apps/live/src/extensions/database.ts",
    'import { getPageService } from "@/services/page/handler";',
    'import { getPageService } from "@/services/page/handler";\n'
    'import { assertChannelAccess } from "@/services/chat-channel.service";',
)
patch(
    "apps/live/src/extensions/database.ts",
    "const fetchDocument = async ({ context, documentName: pageId, instance }: FetchPayloadWithContext) => {\n  try {",
    "const fetchDocument = async ({ context, documentName: pageId, instance }: FetchPayloadWithContext) => {\n"
    '  if (context.documentType === "channel") {\n'
    "    await assertChannelAccess(context, pageId);\n"
    "    // null = no update to apply. An empty Uint8Array is NOT a valid Yjs\n"
    "    // update: Hocuspocus tries to apply it, lib0 throws 'Unexpected end of\n"
    "    // array' and the client gets kicked with permission-denied.\n"
    "    return null;\n"
    "  }\n"
    "  try {",
)
patch(
    "apps/live/src/extensions/database.ts",
    "}: StorePayloadWithContext) => {\n  try {",
    "}: StorePayloadWithContext) => {\n"
    '  if (context.documentType === "channel") return; // nothing to persist\n'
    "  try {",
)

# 6. TitleSync loads page details on every document — skip channel docs.
patch(
    "apps/live/src/extensions/title-sync.ts",
    "  async onLoadDocument({ context, document, documentName }: OnLoadDocumentPayloadWithContext) {",
    "  async onLoadDocument({ context, document, documentName }: OnLoadDocumentPayloadWithContext) {\n"
    '    if (context.documentType === "channel") return;',
)

# 7. Register the broadcast controller (file copied in by the deploy flow)
patch(
    "apps/live/src/controllers/index.ts",
    'import { PdfExportController } from "./pdf-export.controller";',
    'import { PdfExportController } from "./pdf-export.controller";\n'
    'import { ChatBroadcastController } from "./chat.controller";',
)
patch(
    "apps/live/src/controllers/index.ts",
    "export const CONTROLLERS = [CollaborationController, DocumentController, HealthController, PdfExportController];",
    "export const CONTROLLERS = [CollaborationController, DocumentController, HealthController, PdfExportController, ChatBroadcastController];",
)

print("ALL LIVE CHAT PATCHES APPLIED")
