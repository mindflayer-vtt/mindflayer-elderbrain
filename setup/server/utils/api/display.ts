import { Readable } from "node:stream";
import type { H3Event } from "h3";
import { command, backupUpload } from "../management";
import { validate } from "../config";
import { apiBody } from "../api-route";

export async function displayApi(event: H3Event, route: string) {
  const method = event.method;
  const socket = process.env.MANAGEMENT_SOCKET || "/run/elderbrain/management.sock";
  const body = () => apiBody(event);
  if (route === "display-preview" && method === "GET") {
    const result = await command(socket, "display-preview-status");
    if (!result.ok) throw new Error("Display preview status unavailable");
    return JSON.parse(result.output || "{}");
  }
  if (route === "display-preview" && method === "POST") {
    const candidate = Buffer.from(JSON.stringify(validate(await body())));
    const result = await backupUpload(socket, Readable.from([candidate]), candidate.length, "display-preview-start");
    if (!result.ok) throw new Error("Unable to start display preview. Check its status before retrying.");
    setResponseStatus(event, 202);
    return JSON.parse(result.output || "{}");
  }
  if (["display-preview/confirm", "display-preview/cancel"].includes(route) && method === "POST") {
    const input = await body() as { id?: unknown };
    if (typeof input.id !== "string" || !/^[a-f0-9]{32}$/.test(input.id)) throw new Error("Invalid display preview ID");
    const result = await command(socket, route.endsWith("/confirm") ? "display-preview-confirm " + input.id : "display-preview-cancel " + input.id);
    if (!result.ok) throw new Error("Preview is no longer pending, expired, or could not be updated. Refresh its status.");
    return JSON.parse(result.output || "{}");
  }
  if (route === "displays" && method === "GET") {
    const result = await command(socket, "host-displays");
    if (!result.ok) throw new Error("Host display discovery unavailable");
    return JSON.parse(result.output || "{}");
  }

  setResponseStatus(event, 404);
  return { error: "not found" };
}
