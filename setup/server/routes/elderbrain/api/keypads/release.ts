import { apiRoute, unsupportedMethod } from "../../../../utils/api-route";
import { installableRelease } from "../../../../services/keypads";

export default apiRoute(event => event.method === "GET" ? installableRelease() : unsupportedMethod(event));
