import { apiRoute, unsupportedMethod } from "../../../utils/api-route";
import { jobs } from "../../../services/backups";

export default apiRoute(async event => {
  if (event.method !== "GET") return unsupportedMethod(event);
  const result = await jobs();
  if (!result.ok) { setResponseStatus(event, 503); return { error: result.error || "Host jobs unavailable" }; }
  return JSON.parse(result.output || "null");
});
