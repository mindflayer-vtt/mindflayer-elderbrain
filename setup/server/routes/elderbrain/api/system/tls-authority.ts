import { apiRoute, apiBody, unsupportedMethod } from "../../../../utils/api-route";
import { installAuthority } from "../../../../services/tls-authority";

export default apiRoute(async event => {
  if (event.method !== "POST") return unsupportedMethod(event);
  return installAuthority(await apiBody(event));
});
