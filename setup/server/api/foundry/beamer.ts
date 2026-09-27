import { apiRoute } from "../../utils/api-route";
import { foundryApi } from "../../utils/api/foundry";

export default apiRoute(event => foundryApi(event, "foundry/beamer"));
