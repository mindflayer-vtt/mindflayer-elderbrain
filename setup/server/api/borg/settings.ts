import { apiRoute } from "../../utils/api-route";
import { borgApi } from "../../utils/api/borg";

export default apiRoute(event => borgApi(event, "borg/settings"));
