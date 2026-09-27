import { apiRoute, unsupportedMethod } from "../../../../utils/api-route";
import { apiBody } from "../../../../utils/api-route";
import { startBackup } from "../../../../services/backups";

export default apiRoute(async event => {
  if (event.method !== "POST") return unsupportedMethod(event);
  const result = await startBackup(await apiBody(event) as Parameters<typeof startBackup>[0]);
  if (!result.ok) { setResponseStatus(event, 503); return { error: result.error || "Host jobs unavailable" }; }
  setResponseStatus(event, 202);
  return JSON.parse(result.output || "null");
});
