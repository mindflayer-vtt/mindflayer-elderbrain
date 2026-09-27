import { apiRoute, unsupportedMethod } from "../../../../utils/api-route";
import { apiBody } from "../../../../utils/api-route";
import { provisionKeypad } from "../../../../services/keypads";

export default apiRoute(async event => {
  if (event.method !== "POST") return unsupportedMethod(event);
  const result = await provisionKeypad(await apiBody(event) as Record<string, unknown>);
  setResponseStatus(event, 202);
  return result;
});
