import { apiRoute, unsupportedMethod } from "../../../../utils/api-route";
import { apiBody } from "../../../../utils/api-route";
import { backupBorg } from "../../../../services/borg";

export default apiRoute(async event => {
  if (event.method !== "POST") return unsupportedMethod(event);
  const result = await backupBorg(await apiBody(event) as Parameters<typeof backupBorg>[0]);
  setResponseStatus(event, 202);
  return result;
});
