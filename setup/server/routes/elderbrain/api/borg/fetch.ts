import { apiRoute, unsupportedMethod } from "../../../../utils/api-route";
import { apiBody } from "../../../../utils/api-route";
import { fetchBorg } from "../../../../services/borg";

export default apiRoute(async event => {
  if (event.method !== "POST") return unsupportedMethod(event);
  const result = await fetchBorg(await apiBody(event) as Parameters<typeof fetchBorg>[0]);
  setResponseStatus(event, 202);
  return result;
});
