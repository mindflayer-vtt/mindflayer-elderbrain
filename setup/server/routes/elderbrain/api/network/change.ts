import { apiRoute, apiBody, unsupportedMethod } from "../../../../utils/api-route";
import { networkChangeStatus, stageNetworkChange } from "../../../../services/network";

export default apiRoute(async event => {
  if (event.method === "GET") return networkChangeStatus();
  if (event.method === "POST") {
    const result = await stageNetworkChange(await apiBody(event));
    setResponseStatus(event, 202);
    return result;
  }
  return unsupportedMethod(event);
});
