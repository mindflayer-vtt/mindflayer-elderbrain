import { apiRoute, apiBody, unsupportedMethod } from "../../../../utils/api-route";
import { checkRelease } from "../../../../services/system";

export default apiRoute(event => event.method === "POST" ? apiBody(event).then(checkRelease) : unsupportedMethod(event));
