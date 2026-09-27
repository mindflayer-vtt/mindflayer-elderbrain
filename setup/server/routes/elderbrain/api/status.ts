import { apiRoute, unsupportedMethod } from "../../../utils/api-route";
import { applianceStatus } from "../../../services/status";

export default apiRoute(event => event.method === "GET" ? applianceStatus() : unsupportedMethod(event));
