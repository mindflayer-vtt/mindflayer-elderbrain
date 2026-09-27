import { authRoute, requireAuthMethod } from "../../../../utils/auth-route";

export default authRoute((event, auth, id) => {
  requireAuthMethod(event, "GET");
  return auth.session(id);
});
