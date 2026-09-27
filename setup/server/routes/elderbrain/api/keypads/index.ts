import { apiRoute, unsupportedMethod } from "../../../../utils/api-route";
import { registeredKeypads } from "../../../../services/keypads";
import type { KeypadInventory } from "../../../../services/keypad-inventory";

export default apiRoute(async event => {
  if (event.method !== "GET") return unsupportedMethod(event);
  const { keypads, inventorySource, installationSource } = await registeredKeypads(event.context.inventory as KeypadInventory);
  setHeader(event, "x-elderbrain-inventory-source", inventorySource);
  setHeader(event, "x-elderbrain-installation-source", installationSource);
  return keypads;
});
