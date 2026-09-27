import { authRoute, authorizeAuthChange, requireAuthMethod } from "../../../../utils/auth-route";
import { smallBody } from "../../../../utils/request-body";

export default authRoute(async (event, auth, id) => {
  requireAuthMethod(event, "POST");
  const body = await smallBody(event);
  authorizeAuthChange(event, auth, id);
  auth.changePassword(id!, body.currentPassword, body.password);
  deleteCookie(event, "elderbrain-session", { path: "/" });
  return { ok: true };
});
