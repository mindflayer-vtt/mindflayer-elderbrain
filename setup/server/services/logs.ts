import { command } from "./management-client";

export async function foundryLogs() {
  const socket = process.env.MANAGEMENT_SOCKET || "/run/elderbrain/management.sock";
  const result = await command(socket, "foundry-logs");
  if (!result.ok) throw new Error(result.error || "Unable to read Foundry logs");
  return result.output || "";
}
