import { AuthError, type AuthStore } from "../utils/auth";

export default defineEventHandler((event) => {
  const pathname = event.path.split("?")[0]!.replace(/^\/elderbrain(?=\/)/, "");
  if (!pathname.startsWith("/api/")) return;
  setHeader(event, "cache-control", "no-store");
  const devHTTP = process.env.ELDERBRAIN_DEV_HTTP === "1";
  const secure = getHeader(event, "x-forwarded-proto") === "https" || !!(event.node.req.socket as { encrypted?: boolean }).encrypted;
  const mutation = !["GET", "HEAD"].includes(event.method);
  try {
    if (!secure && !devHTTP) throw new AuthError("Use HTTPS for administration", 403);
    if (mutation) {
      const origin = getHeader(event, "origin");
      if (getHeader(event, "x-elderbrain-request") !== "1") throw new AuthError("Same-origin request header required", 403);
      if (origin && new URL(origin).host !== getHeader(event, "host")) throw new AuthError("Cross-origin request rejected", 403);
    }
    const auth = event.context.auth as AuthStore;
    // Keyboard routes independently require a private local-kiosk capability.
    if (["/api/keyboard", "/api/auth/session", "/api/auth/login", "/api/auth/recover", "/api/auth/reset"].includes(pathname)) return;
    auth.authorize(getCookie(event, "elderbrain-session"), getHeader(event, "x-csrf-token"), mutation, pathname.startsWith("/api/auth/"));
  } catch (error) {
    setResponseStatus(event, error instanceof AuthError ? error.statusCode : 403);
    return { error: error instanceof Error ? error.message : "Access denied" };
  }
});
