import { apiRoute, unsupportedMethod } from "../../../../utils/api-route";
import { apiBody } from "../../../../utils/api-route";
import { installKeypad } from "../../../../services/keypads";

export default apiRoute(async event => {
  if (event.method !== "POST") return unsupportedMethod(event);
  const result = await installKeypad(await apiBody(event) as Record<string, unknown>);
  setResponseStatus(event, 202);
  return result;
});
