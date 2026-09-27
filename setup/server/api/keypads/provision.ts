import { apiRoute } from "../../utils/api-route";
import { keypadsApi } from "../../utils/api/keypads";

export default apiRoute(event => keypadsApi(event, "keypads/provision"));
