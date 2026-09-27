import { apiRoute } from "../../utils/api-route";
import { snapshotsApi } from "../../utils/api/snapshots";

export default apiRoute(event => snapshotsApi(event, "snapshots/restore"));
