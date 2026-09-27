import { authRoute, requireAuthMethod } from "../../../../utils/auth-route";
import { smallBody } from "../../../../utils/request-body";

export default authRoute(async (event, auth, _id, client) => {
  requireAuthMethod(event, "POST");
  const body = await smallBody(event);
  const login = auth.login(body.username, body.password, client);
  setCookie(event, "elderbrain-session", login.id, { httpOnly: true, secure: process.env.ELDERBRAIN_DEV_HTTP !== "1",
    sameSite: "strict", path: "/", maxAge: 8 * 60 * 60 });
  const { id: _sessionId, ...session } = login;
  return session;
});
