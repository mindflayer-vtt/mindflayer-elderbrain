import { apiRoute, unsupportedMethod } from "../../../../utils/api-route";
import { apiBody } from "../../../../utils/api-route";
import { configureFoundry } from "../../../../services/foundry";

export default apiRoute(event => event.method === "PUT"
  ? apiBody(event).then(configureFoundry) : unsupportedMethod(event));
