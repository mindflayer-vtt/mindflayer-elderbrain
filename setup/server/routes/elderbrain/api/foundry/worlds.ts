import { apiRoute, unsupportedMethod } from "../../../../utils/api-route";
import { worlds } from "../../../../services/foundry";

export default apiRoute(event => event.method === "GET" ? worlds() : unsupportedMethod(event));
