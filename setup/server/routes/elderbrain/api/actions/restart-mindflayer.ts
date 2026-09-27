import { apiRoute, unsupportedMethod } from "../../../../utils/api-route";
import { restartService } from "../../../../services/actions";

export default apiRoute(event => event.method === "POST" ? restartService("restart-mindflayer") : unsupportedMethod(event));
