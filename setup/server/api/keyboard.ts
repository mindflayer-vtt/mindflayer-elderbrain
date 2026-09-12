import { command } from "../utils/management";
import { smallBody } from "../utils/request-body";

export default defineEventHandler(async (event) => {
  const token = getHeader(event, "x-kiosk-keyboard") || "";
  if (!/^[a-f0-9]{64}$/.test(token)) throw createError({ statusCode: 403, statusMessage: "Use the local appliance keyboard selector" });
  if (!["GET", "POST"].includes(event.method)) throw createError({ statusCode: 405 });
  let selected: string | undefined;
  if (event.method === "POST") {
    const body = await smallBody(event);
    if (typeof body.layout !== "string" || !/^[a-z0-9_-]{1,32}:[a-z0-9_-]{0,64}$/.test(body.layout))
      throw createError({ statusCode: 400, statusMessage: "Invalid keyboard layout" });
    selected = body.layout;
  }
  const result = await command(process.env.MANAGEMENT_SOCKET || "/run/elderbrain/management.sock",
    `kiosk-keyboard ${token}${selected === undefined ? "" : " " + selected}`);
  if (!result.ok) throw createError({ statusCode: 403, statusMessage: "Local keyboard selection is unavailable" });
  return JSON.parse(result.output || "{}");
});
