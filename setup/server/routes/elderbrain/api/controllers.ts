import { apiRoute, unsupportedMethod } from "../../../utils/api-route";
import type { ControllerMonitor } from "../../../services/controller-monitor";

export default apiRoute(event => event.method === "GET"
  ? (event.context.monitor as ControllerMonitor).snapshot() : unsupportedMethod(event));
