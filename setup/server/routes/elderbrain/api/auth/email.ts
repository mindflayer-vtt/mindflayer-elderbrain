import { authRoute, authorizeAuthChange, requireAuthMethod } from "../../../../utils/auth-route";
import { smallBody } from "../../../../utils/request-body";

export default authRoute(async (event, auth, id) => {
  requireAuthMethod(event, "POST");
  const body = await smallBody(event);
  authorizeAuthChange(event, auth, id);
  await auth.configureEmail(body.email, body.smtp);
  return { ok: true };
});
