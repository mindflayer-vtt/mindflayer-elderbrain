import { apiRoute, unsupportedMethod } from "../../../../utils/api-route";
import { apiBody } from "../../../../utils/api-route";
import { recoverSnapshots } from "../../../../services/snapshots";

export default apiRoute(async event => {
  if (event.method !== "POST") return unsupportedMethod(event);
  const result = await recoverSnapshots(await apiBody(event) as Parameters<typeof recoverSnapshots>[0]);
  setResponseStatus(event, 202);
  return result;
});
