import { apiRoute, unsupportedMethod } from "../../../../utils/api-route";
import { apiBody } from "../../../../utils/api-route";
import { previewEncryptedBackup } from "../../../../services/backups";

export default apiRoute(async event => {
  if (event.method !== "POST") return unsupportedMethod(event);
  const result = await previewEncryptedBackup(await apiBody(event) as Parameters<typeof previewEncryptedBackup>[0]);
  setResponseStatus(event, 202);
  return result;
});
