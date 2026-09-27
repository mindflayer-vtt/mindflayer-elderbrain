import { authRoute, requireAuthMethod } from "../../../../utils/auth-route";
import { smallBody } from "../../../../utils/request-body";

export default authRoute(async (event, auth, _id, client) => {
  requireAuthMethod(event, "POST");
  const body = await smallBody(event);
  auth.resetPassword(body.token, body.password, client);
  return { ok: true };
});
