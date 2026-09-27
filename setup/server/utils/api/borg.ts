import { Readable } from "node:stream";
import type { H3Event } from "h3";
import { command, backupDownload, backupUpload } from "../management";
import { apiBody } from "../api-route";

export async function borgApi(event: H3Event, route: string) {
  const method = event.method;
  const socket = process.env.MANAGEMENT_SOCKET || "/run/elderbrain/management.sock";
  const body = () => apiBody(event);
  const kit = /^borg\/recovery-kits\/([0-9a-f]{32})\/download$/.exec(route);
  if (kit && method === "GET") {
    const result = await backupDownload(socket, kit[1]!, "recovery-download");
    setHeader(event, "content-type", "application/json");
    setHeader(event, "content-length", result.size);
    setHeader(event, "content-disposition", `attachment; filename="elderbrain-recovery-${kit[1]}.json"`);
    return sendStream(event, result.stream);
  }
  if (route === "borg/settings" && ["GET", "PUT"].includes(method)) {
    const data = method === "PUT" ? Buffer.from(JSON.stringify(await body())) : undefined;
    const result = data ? await backupUpload(socket, Readable.from([data]), data.length, "borg-configure") : await command(socket, "borg-settings");
    if (!result.ok) throw new Error(result.error || "Borg settings unavailable");
    return JSON.parse(result.output || "null");
  }
  const borgAction = /^borg\/(init|test|list|backup|fetch|recovery-kit)$/.exec(route);
  if (borgAction && method === "POST") {
    const input = await body() as { confirm?: boolean; archive?: string };
    if (["init", "recovery-kit"].includes(borgAction[1]!) && input.confirm !== true) throw new Error("This repository operation requires explicit confirmation");
    if (borgAction[1] === "fetch" && (typeof input.archive !== "string" || !/^elderbrain-[A-Za-z0-9_.:+-]{1,200}$/.test(input.archive))) throw new Error("Invalid archive name");
    const result = await command(socket, `borg-${borgAction[1]}-start` + (borgAction[1] === "fetch" ? " " + input.archive : ""));
    if (!result.ok) throw new Error(result.error || "Borg operation unavailable");
    setResponseStatus(event, 202);
    return JSON.parse(result.output || "null");
  }

  setResponseStatus(event, 404);
  return { error: "not found" };
}
