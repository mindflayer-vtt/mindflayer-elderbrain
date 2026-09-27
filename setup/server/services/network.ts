import { Readable } from "node:stream";
import { command, backupUpload } from "./management-client";

const socket = () => process.env.MANAGEMENT_SOCKET || "/run/elderbrain/management.sock";

export async function networkChangeStatus() {
  const result = await command(socket(), "network-status");
  if (!result.ok) throw new Error("Network change status unavailable");
  return JSON.parse(result.output || "{}");
}

export async function stageNetworkChange(input: unknown) {
  const candidate = Buffer.from(JSON.stringify(input));
  if (candidate.length > 2048) throw new Error("Network settings are too large");
  const result = await backupUpload(socket(), Readable.from([candidate]), candidate.length, "network-start");
  if (!result.ok) throw new Error("Unable to stage network changes. Check status before retrying.");
  return JSON.parse(result.output || "{}");
}

export async function cancelNetworkChange(input: { id?: unknown }) {
  if (typeof input?.id !== "string" || !/^[a-f0-9]{32}$/.test(input.id)) throw new Error("Invalid network change ID");
  const result = await command(socket(), "network-cancel " + input.id);
  if (!result.ok) throw new Error("Network change could not be reverted. Refresh its status.");
  return JSON.parse(result.output || "{}");
}

export async function hostNetwork() {
  const result = await command(socket(), "host-network");
  if (!result.ok) throw new Error("Host network discovery unavailable");
  return JSON.parse(result.output || "{}");
}
