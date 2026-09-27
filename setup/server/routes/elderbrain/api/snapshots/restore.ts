import { apiRoute, unsupportedMethod } from "../../../../utils/api-route";
import { apiBody } from "../../../../utils/api-route";
import { restoreSnapshot } from "../../../../services/snapshots";

export default apiRoute(async event => {
  if (event.method !== "POST") return unsupportedMethod(event);
  const result = await restoreSnapshot(await apiBody(event) as Parameters<typeof restoreSnapshot>[0]);
  setResponseStatus(event, 202);
  return result;
});
