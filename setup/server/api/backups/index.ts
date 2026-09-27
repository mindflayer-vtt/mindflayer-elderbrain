import { apiRoute } from "../../utils/api-route";
import { backupsApi } from "../../utils/api/backups";

export default apiRoute(event => backupsApi(event, "backups"));
