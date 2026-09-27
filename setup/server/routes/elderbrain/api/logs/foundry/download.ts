import { apiRoute, unsupportedMethod } from "../../../../../utils/api-route";
import { foundryLogs } from "../../../../../services/logs";

export default apiRoute(async event => {
  if (event.method !== "GET") return unsupportedMethod(event);
  try {
    const output = await foundryLogs();
    setHeader(event, "content-type", "text/plain; charset=utf-8");
    setHeader(event, "content-disposition", 'attachment; filename="foundry-recent.log"');
    return output;
  } catch (error) { setResponseStatus(event, 503); return { error: (error as Error).message }; }
});
