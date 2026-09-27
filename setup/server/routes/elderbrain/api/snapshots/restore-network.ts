import { apiRoute, unsupportedMethod } from "../../../../utils/api-route";
import { apiBody } from "../../../../utils/api-route";
import { restoreNetwork } from "../../../../services/snapshots";

export default apiRoute(event => event.method === "POST"
  ? apiBody(event).then(input => restoreNetwork(input as Parameters<typeof restoreNetwork>[0]))
  : unsupportedMethod(event));
