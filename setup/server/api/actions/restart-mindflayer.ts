import { apiRoute } from "../../utils/api-route";
import { miscApi } from "../../utils/api/misc";

export default apiRoute(event => miscApi(event, "actions/restart-mindflayer"));
