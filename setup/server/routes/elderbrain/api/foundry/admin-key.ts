import { apiRoute, unsupportedMethod } from "../../../../utils/api-route";
import { apiBody } from "../../../../utils/api-route";
import { adminKey, resetAdminKey } from "../../../../services/foundry";

export default apiRoute(event => {
  if (event.method === "GET") return adminKey();
  if (event.method === "POST") return apiBody(event).then(resetAdminKey);
  return unsupportedMethod(event);
});
