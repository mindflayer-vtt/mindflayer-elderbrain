import type { H3Event } from "h3";
import { AuthError, type AuthStore } from "../services/auth-store";
import { clientAddress } from "./client-address";

export function authRoute(handler: (event: H3Event, auth: AuthStore, id: string | undefined, client: string) => unknown | Promise<unknown>) {
  return defineEventHandler(async event => {
    try {
      const client = clientAddress(event.node.req.socket.remoteAddress, getHeader(event, "x-forwarded-for"),
        process.env.ELDERBRAIN_DEV_HTTP === "1", process.env.ELDERBRAIN_TRUSTED_PROXY_IP);
      return await handler(event, event.context.auth as AuthStore, getCookie(event, "elderbrain-session"), client);
    } catch (error) {
      setResponseStatus(event, error instanceof AuthError ? error.statusCode : 400);
      return { error: error instanceof Error ? error.message : "Request failed" };
    }
  });
}

export function requireAuthMethod(event: H3Event, method: "GET" | "POST") {
  if (event.method !== method) throw new AuthError("Not found", 404);
}

export function authorizeAuthChange(event: H3Event, auth: AuthStore, id: string | undefined) {
  auth.authorize(id, getHeader(event, "x-csrf-token"), true, true);
}
