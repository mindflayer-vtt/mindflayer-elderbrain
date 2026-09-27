import { apiRoute, apiBody, unsupportedMethod } from "../../../../utils/api-route";
import { confirmPreview } from "../../../../services/display";

export default apiRoute(event => event.method === "POST"
  ? apiBody(event).then(input => confirmPreview(input as { id?: unknown }))
  : unsupportedMethod(event));
