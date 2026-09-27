import { apiRoute, apiBody, unsupportedMethod } from "../../../../utils/api-route";
import { previewStatus, startPreview } from "../../../../services/display";

export default apiRoute(async event => {
  if (event.method === "GET") return previewStatus();
  if (event.method === "POST") {
    const result = await startPreview(await apiBody(event));
    setResponseStatus(event, 202);
    return result;
  }
  return unsupportedMethod(event);
});
