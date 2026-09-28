import { apiRoute, apiBody, unsupportedMethod } from "../../../../utils/api-route";
import { keyboardSettings } from "../../../../services/keyboard";

export default apiRoute(async event => {
  if (event.method === "GET") return keyboardSettings();
  if (event.method === "PUT") {
    const body = await apiBody(event) as { layout?: unknown };
    if (body.layout === undefined) throw new Error("Keyboard layout is required");
    return keyboardSettings(body.layout);
  }
  return unsupportedMethod(event);
});
