import { apiRoute, unsupportedMethod } from "../../../../utils/api-route";
import { releaseStatus } from "../../../../services/system";

export default apiRoute(event => event.method === "GET" ? releaseStatus() : unsupportedMethod(event));
