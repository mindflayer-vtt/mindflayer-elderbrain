import { apiRoute, unsupportedMethod } from "../../../../../../utils/api-route";
import { downloadRecoveryKit } from "../../../../../../services/borg";

export default apiRoute(async event => {
  if (event.method !== "GET") return unsupportedMethod(event);
  const id = getRouterParam(event, "id") || "";
  if (!/^[0-9a-f]{32}$/.test(id)) return unsupportedMethod(event);
  const result = await downloadRecoveryKit(id);
  if (!result) return unsupportedMethod(event);
  setHeader(event, "content-type", "application/json");
  setHeader(event, "content-length", result.size);
  setHeader(event, "content-disposition", `attachment; filename="elderbrain-recovery-${id}.json"`);
  return sendStream(event, result.stream);
});
