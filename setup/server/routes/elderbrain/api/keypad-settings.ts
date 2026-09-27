import { apiRoute, unsupportedMethod } from "../../../utils/api-route";
import { apiBody } from "../../../utils/api-route";
import { keypadSettings, configureKeypads } from "../../../services/keypads";
import type { KeypadInventory } from "../../../services/keypad-inventory";

export default apiRoute(event => {
  const inventory = event.context.inventory as KeypadInventory;
  if (event.method === "GET") return keypadSettings(inventory);
  if (event.method === "PUT") return apiBody(event).then(input => configureKeypads(inventory, input as Record<string, unknown>));
  return unsupportedMethod(event);
});
