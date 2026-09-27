import { apiRoute, unsupportedMethod } from "../../../utils/api-route";
import { hostDisplays } from "../../../services/display";

export default apiRoute(event => event.method === "GET" ? hostDisplays() : unsupportedMethod(event));
