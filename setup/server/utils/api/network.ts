import { Readable } from "node:stream";
import type { H3Event } from "h3";
import { command, backupUpload } from "../management";
import { apiBody } from "../api-route";

export async function networkApi(event: H3Event, route: string) {
  const method = event.method;
  const socket = process.env.MANAGEMENT_SOCKET || "/run/elderbrain/management.sock";
  const body = () => apiBody(event);
  if (route === "network/change" && method === "GET") {
    const result = await command(socket, "network-status");
    if (!result.ok) throw new Error("Network change status unavailable");
    return JSON.parse(result.output || "{}");
  }
  if (route === "network/change" && method === "POST") {
    const candidate = Buffer.from(JSON.stringify(await body()));
    if (candidate.length > 2048) throw new Error("Network settings are too large");
    const result = await backupUpload(socket, Readable.from([candidate]), candidate.length, "network-start");
    if (!result.ok) throw new Error("Unable to stage network changes. Check status before retrying.");
    setResponseStatus(event, 202);
    return JSON.parse(result.output || "{}");
  }
  if (route === "network/change/cancel" && method === "POST") {
    const input = await body() as { id?: unknown };
    if (typeof input?.id !== "string" || !/^[a-f0-9]{32}$/.test(input.id)) throw new Error("Invalid network change ID");
    const result = await command(socket, "network-cancel " + input.id);
    if (!result.ok) throw new Error("Network change could not be reverted. Refresh its status.");
    return JSON.parse(result.output || "{}");
  }

  if (route === "network" && method === "GET") {
    const result = await command(socket, "host-network");
    if (!result.ok) throw new Error("Host network discovery unavailable");
    return JSON.parse(result.output || "{}");
  }

  setResponseStatus(event, 404);
  return { error: "not found" };
}
