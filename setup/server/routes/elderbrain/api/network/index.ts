import { apiRoute, unsupportedMethod } from "../../../../utils/api-route";
import { hostNetwork } from "../../../../services/network";

export default apiRoute(event => event.method === "GET" ? hostNetwork() : unsupportedMethod(event));
