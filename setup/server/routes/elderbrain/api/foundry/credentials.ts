import { apiRoute, unsupportedMethod } from "../../../../utils/api-route";
import { deleteCredentials } from "../../../../services/foundry";

export default apiRoute(event => event.method === "DELETE" ? deleteCredentials() : unsupportedMethod(event));
