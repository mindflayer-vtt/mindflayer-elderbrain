import { apiRoute } from "../../../utils/api-route";
import { miscApi } from "../../../utils/api/misc";

export default apiRoute(event => miscApi(event, `controllers/${getRouterParam(event, "id")}/identify`));
