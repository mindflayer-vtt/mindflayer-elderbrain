import { apiRoute, unsupportedMethod } from "../../../utils/api-route";
import { currentConfig } from "../../../services/configuration";

export default apiRoute(event => {
  if (event.method === "GET") return currentConfig();
  if (event.method === "PUT") { setResponseStatus(event, 409); return { error: "Configuration changes require a display preview and explicit confirmation" }; }
  return unsupportedMethod(event);
});
