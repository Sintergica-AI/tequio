/**
 * Sintergica CE extension: chat-channel authorization for the live server.
 *
 * A "channel" document holds no CRDT content — the Y.Doc stays empty and the
 * socket only carries stateless JSON events + awareness. That means the
 * Database extension never talks to Django for it, so the resource-level
 * authorization pages get for free (Django rejecting the binary fetch) has to
 * happen explicitly: before accepting the doc we call the chat membership
 * endpoint with the requesting user's cookie. Non-2xx → throw → Hocuspocus
 * drops the connection.
 *
 * Document naming: "chat:<channel uuid>".
 *
 * Derived from Plane CE code (AGPL-3.0-only).
 */

import { AppError } from "@/lib/errors";
import { APIService } from "@/services/api.service";

const DOCUMENT_PREFIX = "chat:";

export const channelIdFromDocumentName = (documentName: string): string | null => {
  if (!documentName.startsWith(DOCUMENT_PREFIX)) return null;
  return documentName.slice(DOCUMENT_PREFIX.length);
};

class ChatChannelService extends APIService {
  constructor(cookie: string) {
    super();
    this.setHeader("Cookie", cookie);
  }

  async assertMembership(workspaceSlug: string, channelId: string): Promise<void> {
    await this.get(
      `/api/workspaces/${workspaceSlug}/chat/channels/${channelId}/membership/`,
      {},
      { headers: this.getHeader() }
    );
  }

  async assertWorkspaceMember(workspaceSlug: string): Promise<void> {
    await this.get(`/api/workspaces/${workspaceSlug}/chat/me/`, {}, { headers: this.getHeader() });
  }
}

type TChannelContext = {
  cookie?: string | null;
  workspaceSlug?: string | null;
  [key: string]: unknown;
};

export const assertChannelAccess = async (context: TChannelContext, documentName: string): Promise<void> => {
  const channelId = channelIdFromDocumentName(documentName);
  if (!channelId) throw new AppError(`Invalid channel document name: ${documentName}`);
  if (!context.cookie) throw new AppError("Cookie is required.");
  if (!context.workspaceSlug) throw new AppError("workspaceSlug is required.");
  const service = new ChatChannelService(context.cookie);
  // The workspace-wide badge document ("chat:workspace:<id>") has no single
  // channel to check — any active workspace member may subscribe, probed via
  // the cheap /chat/me/ endpoint. Per-channel docs check real membership.
  if (channelId.startsWith("workspace:")) {
    await service.assertWorkspaceMember(context.workspaceSlug);
    return;
  }
  // AppError from the interceptor bubbles up and closes the connection.
  await service.assertMembership(context.workspaceSlug, channelId);
};
