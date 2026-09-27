import { apiRoute, apiBody, unsupportedMethod } from "../../../../../utils/api-route";
import { cancelNetworkChange } from "../../../../../services/network";

export default apiRoute(event => event.method === "POST"
  ? apiBody(event).then(input => cancelNetworkChange(input as { id?: unknown }))
  : unsupportedMethod(event));
