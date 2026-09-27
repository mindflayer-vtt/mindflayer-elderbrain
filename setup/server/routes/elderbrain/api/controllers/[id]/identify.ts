import { apiRoute, unsupportedMethod } from "../../../../../utils/api-route";
import type { ControllerMonitor } from "../../../../../services/controller-monitor";

export default apiRoute(event => {
  if (event.method !== "POST") return unsupportedMethod(event);
  (event.context.monitor as ControllerMonitor).identify(decodeURIComponent(getRouterParam(event, "id") || ""));
  return { sent: true };
});
