import { apiRoute, apiBody, unsupportedMethod } from "../../../../utils/api-route";
import { cancelPreview } from "../../../../services/display";

export default apiRoute(event => event.method === "POST"
  ? apiBody(event).then(input => cancelPreview(input as { id?: unknown }))
  : unsupportedMethod(event));
