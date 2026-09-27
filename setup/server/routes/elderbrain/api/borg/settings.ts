import { apiRoute, unsupportedMethod } from "../../../../utils/api-route";
import { apiBody } from "../../../../utils/api-route";
import { borgSettings, configureBorg } from "../../../../services/borg";

export default apiRoute(event => {
  if (event.method === "GET") return borgSettings();
  if (event.method === "PUT") return apiBody(event).then(configureBorg);
  return unsupportedMethod(event);
});
