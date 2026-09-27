import { apiRoute, unsupportedMethod } from "../../../../utils/api-route";
import { apiBody } from "../../../../utils/api-route";
import { beamer, configureBeamer, deleteBeamer } from "../../../../services/foundry";

export default apiRoute(async event => {
  if (event.method === "GET") return beamer();
  if (event.method === "PUT") return configureBeamer(await apiBody(event));
  if (event.method === "DELETE") return deleteBeamer();
  return unsupportedMethod(event);
});
