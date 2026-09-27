import { apiRoute } from "../../../../utils/api-route";
import { networkApi } from "../../../../utils/api/network";

export default apiRoute(event => networkApi(event, "network"));
