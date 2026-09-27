import fs from "node:fs";
import path from "node:path";
import type { H3Event } from "h3";
import { command } from "../management";
import { load } from "../config";
import type { ControllerMonitor } from "../controllers";

export async function miscApi(event: H3Event, route: string) {
  const method = event.method;
  const state = process.env.STATE_DIR || "/state";
  const config = path.join(state, "config.json");
  const socket = process.env.MANAGEMENT_SOCKET || "/run/elderbrain/management.sock";
  const monitor = event.context.monitor as ControllerMonitor;
  if ((route === "logs/foundry" || route === "logs/foundry/download") && method === "GET") {
    const result = await command(socket, "foundry-logs");
    if (!result.ok) {
      setResponseStatus(event, 503);
      return { error: result.error || "Unable to read Foundry logs" };
    }
    if (route.endsWith("/download")) {
      setHeader(event, "content-type", "text/plain; charset=utf-8");
      setHeader(event, "content-disposition", 'attachment; filename="foundry-recent.log"');
      return result.output || "";
    }
    return { output: result.output || "", updatedAt: new Date().toISOString() };
  }
  if (route === "config" && method === "GET") return load(config);
  if (route === "config" && method === "PUT") {
    setResponseStatus(event, 409);
    return { error: "Configuration changes require a display preview and explicit confirmation" };
  }

  if (route === "controllers" && method === "GET") return monitor.snapshot();
  const identify = /^controllers\/([^/]+)\/identify$/.exec(route);
  if (identify && method === "POST") { monitor.identify(decodeURIComponent(identify[1]!)); return { sent: true }; }
  if (route === "status" && method === "GET") {
    let version = "development";
    try { version = fs.readFileSync(process.env.APPLIANCE_VERSION_FILE || "/opt/elderbrain/VERSION", "utf8").trim(); } catch {}
    const managed = await command(socket, "host-metrics");
    if (!managed.ok) throw new Error("Host metrics unavailable");
    return { version, mindflayerServerImage: process.env.MINDFLAYER_SERVER_IMAGE || "unknown",
      ...JSON.parse(managed.output || "{}") };
  }
  const action = /^actions\/(restart-foundry|restart-mindflayer|restart-browser-session)$/.exec(route);
  if (action && method === "POST") return await command(socket, action[1]!);

  setResponseStatus(event, 404);
  return { error: "not found" };
}
