import { apiRoute, unsupportedMethod } from "../../../../../utils/api-route";
import { downloadBackup } from "../../../../../services/backups";

export default apiRoute(async event => {
  if (event.method !== "GET") return unsupportedMethod(event);
  const id = getRouterParam(event, "id") || "";
  if (!/^[0-9a-f]{32}$/.test(id)) return unsupportedMethod(event);
  const result = await downloadBackup(id);
  if (!result) return unsupportedMethod(event);
  setHeader(event, "content-type", result.encrypted ? "application/octet-stream" : "application/zstd");
  setHeader(event, "content-length", result.size);
  setHeader(event, "content-disposition", `attachment; filename="elderbrain-${id}.tar.zst${result.encrypted ? '.gpg' : ''}"`);
  return sendStream(event, result.stream);
});
