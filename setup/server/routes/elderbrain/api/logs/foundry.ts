import { apiRoute, unsupportedMethod } from "../../../../utils/api-route";
import { foundryLogs } from "../../../../services/logs";

export default apiRoute(async event => {
  if (event.method !== "GET") return unsupportedMethod(event);
  try { return { output: await foundryLogs(), updatedAt: new Date().toISOString() }; }
  catch (error) { setResponseStatus(event, 503); return { error: (error as Error).message }; }
});
