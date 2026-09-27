import { apiRoute } from "../../../../utils/api-route";
import { systemApi } from "../../../../utils/api/system";

export default apiRoute(event => systemApi(event, "system/check"));
