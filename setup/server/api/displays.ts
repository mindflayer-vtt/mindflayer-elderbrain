import { apiRoute } from "../utils/api-route";
import { displayApi } from "../utils/api/display";

export default apiRoute(event => displayApi(event, "displays"));
