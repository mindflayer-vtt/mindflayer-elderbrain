import { apiRoute, unsupportedMethod } from "../../../../utils/api-route";
import { apiBody } from "../../../../utils/api-route";
import { renameKeypad } from "../../../../services/keypads";
import type { ControllerMonitor } from "../../../../services/controller-monitor";
import type { KeypadInventory } from "../../../../services/keypad-inventory";

export default apiRoute(async event => {
  if (event.method !== "PUT") return unsupportedMethod(event);
  const id = getRouterParam(event, "id") || "";
  if (!/^[A-Za-z0-9._-]{1,64}$/.test(id)) return unsupportedMethod(event);
  return renameKeypad(event.context.inventory as KeypadInventory, event.context.monitor as ControllerMonitor,
    id, await apiBody(event) as Record<string, unknown>);
});
