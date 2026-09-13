import { AuthError, type AuthStore } from "../../utils/auth";
import { smallBody } from "../../utils/request-body";
import { clientAddress } from "../../utils/client-address";

export default defineEventHandler(async (event) => {
  const auth = event.context.auth as AuthStore;
  const action = getRouterParam(event, "action");
  const id = getCookie(event, "elderbrain-session");
  try {
    const client = clientAddress(event.node.req.socket.remoteAddress, getHeader(event, "x-forwarded-for"),
      process.env.ELDERBRAIN_DEV_HTTP === "1", process.env.ELDERBRAIN_TRUSTED_PROXY_IP);
    if (action === "session" && event.method === "GET") return auth.session(id);
    if (event.method !== "POST") throw new AuthError("Not found", 404);
    const body = await smallBody(event);
    if (action === "login") {
      const login = auth.login(body.username, body.password, client);
      setCookie(event, "elderbrain-session", login.id, { httpOnly: true, secure: process.env.ELDERBRAIN_DEV_HTTP !== "1",
        sameSite: "strict", path: "/", maxAge: 8 * 60 * 60 });
      const { id: _id, ...session } = login;
      return session;
    }
    if (action === "recover") { await auth.requestRecovery(body.email, client); return { ok: true }; }
    if (action === "reset") { auth.resetPassword(body.token, body.password, client); return { ok: true }; }
    auth.authorize(id, getHeader(event, "x-csrf-token"), true, true);
    if (action === "logout") { auth.logout(id); deleteCookie(event, "elderbrain-session", { path: "/" }); return { ok: true }; }
    if (action === "password") {
      auth.changePassword(id!, body.currentPassword, body.password);
      deleteCookie(event, "elderbrain-session", { path: "/" });
      return { ok: true };
    }
    if (action === "email") { await auth.configureEmail(body.email, body.smtp); return { ok: true }; }
    if (action === "verify") return { recoveryCode: auth.verifyEmail(body.code) };
    throw new AuthError("Not found", 404);
  } catch (error) {
    setResponseStatus(event, error instanceof AuthError ? error.statusCode : 400);
    return { error: error instanceof Error ? error.message : "Request failed" };
  }
});
