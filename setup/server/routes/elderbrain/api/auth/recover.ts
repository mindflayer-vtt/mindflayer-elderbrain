import { authRoute, requireAuthMethod } from "../../../../utils/auth-route";
import { smallBody } from "../../../../utils/request-body";

export default authRoute(async (event, auth, _id, client) => {
  requireAuthMethod(event, "POST");
  const body = await smallBody(event);
  await auth.requestRecovery(body.email, client);
  return { ok: true };
});
