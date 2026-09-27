import { apiRoute, unsupportedMethod } from "../../../../utils/api-route";
import { usbDevices } from "../../../../services/keypads";

export default apiRoute(event => event.method === "GET" ? usbDevices() : unsupportedMethod(event));
