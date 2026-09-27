import fs from "node:fs";
import { command } from "./management-client";

export async function applianceStatus() {
  let version = "development";
  try { version = fs.readFileSync(process.env.APPLIANCE_VERSION_FILE || "/opt/elderbrain/VERSION", "utf8").trim(); } catch {}
  const socket = process.env.MANAGEMENT_SOCKET || "/run/elderbrain/management.sock";
  const managed = await command(socket, "host-metrics");
  if (!managed.ok) throw new Error("Host metrics unavailable");
  return { version, mindflayerServerImage: process.env.MINDFLAYER_SERVER_IMAGE || "unknown",
    ...JSON.parse(managed.output || "{}") };
}
