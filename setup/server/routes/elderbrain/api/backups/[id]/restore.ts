import { apiRoute, unsupportedMethod } from "../../../../../utils/api-route";
import { apiBody } from "../../../../../utils/api-route";
import { restoreBackup } from "../../../../../services/backups";

export default apiRoute(async event => {
  if (event.method !== "POST") return unsupportedMethod(event);
  const id = getRouterParam(event, "id") || "";
  if (!/^[0-9a-f]{32}$/.test(id)) return unsupportedMethod(event);
  const result = await restoreBackup(id, await apiBody(event) as { confirm?: boolean });
  setResponseStatus(event, 202);
  return result;
});
