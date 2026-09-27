import { apiRoute, unsupportedMethod } from "../../../../utils/api-route";
import { apiBody } from "../../../../utils/api-route";
import { listSnapshots, createSnapshot } from "../../../../services/snapshots";

export default apiRoute(async event => {
  if (event.method === "GET") return listSnapshots();
  if (event.method === "POST") {
    const result = await createSnapshot(await apiBody(event) as Parameters<typeof createSnapshot>[0]);
    setResponseStatus(event, 202);
    return result;
  }
  return unsupportedMethod(event);
});
