import { apiRoute, unsupportedMethod } from "../../../../utils/api-route";
import { apiBody } from "../../../../utils/api-route";
import { retention, setRetention } from "../../../../services/snapshots";

export default apiRoute(event => {
  if (event.method === "GET") return retention();
  if (event.method === "PUT") return apiBody(event).then(input => setRetention(input as Parameters<typeof setRetention>[0]));
  return unsupportedMethod(event);
});
