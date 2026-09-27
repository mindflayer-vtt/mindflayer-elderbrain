import { apiRoute, unsupportedMethod } from "../../../../utils/api-route";
import { uploadBackup } from "../../../../services/backups";

export default apiRoute(async event => {
  if (event.method !== "POST") return unsupportedMethod(event);
  const size = Number(getHeader(event, "content-length"));
  if (!Number.isSafeInteger(size) || size <= 0 || size > 1024 ** 4) {
    setResponseStatus(event, 411);
    return { error: "A positive Content-Length up to 1 TiB is required" };
  }
  const result = await uploadBackup(event.node.req, size, true);
  setResponseStatus(event, 202);
  return result;
});
