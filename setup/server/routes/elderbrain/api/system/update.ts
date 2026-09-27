import { apiRoute, apiBody, unsupportedMethod } from "../../../../utils/api-route";
import { startUpdate } from "../../../../services/system";

export default apiRoute(async event => {
  if (event.method !== "POST") return unsupportedMethod(event);
  const result = await startUpdate(await apiBody(event));
  setResponseStatus(event, 202);
  return result;
});
