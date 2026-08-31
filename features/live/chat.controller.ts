/**
 * Sintergica CE extension: HTTP broadcast endpoint for chat events.
 *
 * Django (celery task) POSTs here after committing a message/reaction; the
 * event fans out to every client connected to the channel's document via the
 * Redis extension (multi-node) or directly (single node without Redis). If no
 * client holds the document, the publish simply has no subscribers — offline
 * clients catch up over REST when they reconnect.
 *
 * Protected by the shared live-server-secret-key header, same as the other
 * internal endpoints.
 *
 * Derived from Plane CE code (AGPL-3.0-only).
 */

import type { Hocuspocus } from "@hocuspocus/server";
import type { Request, Response } from "express";
import { z } from "zod";
// plane imports
import { Controller, Middleware, Post } from "@plane/decorators";
import { logger } from "@plane/logger";
// extensions
import { Redis } from "@/extensions/redis";
// lib
import { requireSecretKey } from "@/lib/auth-middleware";

const broadcastSchema = z.object({
  document_name: z.string().min(1),
  payload: z.record(z.unknown()),
});

@Controller("/broadcast")
export class ChatBroadcastController {
  [key: string]: unknown;
  private readonly hocusPocusServer: Hocuspocus;

  constructor(hocusPocusServer: Hocuspocus) {
    this.hocusPocusServer = hocusPocusServer;
  }

  @Post("/")
  @Middleware(requireSecretKey)
  async broadcast(req: Request, res: Response) {
    try {
      const { document_name, payload } = broadcastSchema.parse(req.body);
      const stringPayload = JSON.stringify(payload);

      const redisExtension = this.hocusPocusServer.configuration.extensions.find((ext) => ext instanceof Redis);
      if (redisExtension) {
        const receivers = await redisExtension.broadcastToDocument(document_name, stringPayload);
        return res.status(200).json({ delivered: true, receivers });
      }

      // Single-node fallback: deliver to the locally loaded document, if any.
      const document = this.hocusPocusServer.documents.get(document_name);
      if (document) document.broadcastStateless(stringPayload);
      return res.status(200).json({ delivered: !!document, receivers: document ? 1 : 0 });
    } catch (error) {
      if (error instanceof z.ZodError) {
        return res.status(400).json({ message: "Validation error", context: error.errors });
      }
      logger.error("CHAT_BROADCAST_CONTROLLER: error broadcasting", error);
      return res.status(500).json({ message: "Internal server error" });
    }
  }
}
