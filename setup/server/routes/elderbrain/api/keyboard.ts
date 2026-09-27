import { keyboardLayout } from "../../../services/keyboard";
import { smallBody } from "../../../utils/request-body";

export default defineEventHandler(async (event) => {
  const token = getHeader(event, "x-kiosk-keyboard") || "";
  if (!/^[a-f0-9]{64}$/.test(token)) throw createError({ statusCode: 403, statusMessage: "Use the local appliance keyboard selector" });
  if (!["GET", "POST"].includes(event.method)) throw createError({ statusCode: 405 });
  let selected: unknown;
  if (event.method === "POST") {
    const body = await smallBody(event);
    selected = body.layout;
  }
  try { return await keyboardLayout(token, selected, event.method === "POST"); }
  catch (error) {
    if (error instanceof Error && error.message === "Invalid keyboard layout")
      throw createError({ statusCode: 400, statusMessage: error.message });
    if (error instanceof Error && error.message === "Local keyboard selection is unavailable")
      throw createError({ statusCode: 403, statusMessage: error.message });
    throw error;
  }
});
