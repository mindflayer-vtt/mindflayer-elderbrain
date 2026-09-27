import { apiRoute, apiBody, unsupportedMethod } from "../../../../utils/api-route";
import { powerStatus, requestPower } from "../../../../services/system";

export default apiRoute(async event => {
  if (event.method === "GET") return powerStatus();
  if (event.method === "POST") {
    const result = await requestPower(await apiBody(event));
    setResponseStatus(event, 202);
    return result;
  }
  return unsupportedMethod(event);
});
