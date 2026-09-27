import { command } from "./management-client";

export function restartService(action: "restart-foundry" | "restart-mindflayer" | "restart-browser-session") {
  return command(process.env.MANAGEMENT_SOCKET || "/run/elderbrain/management.sock", action);
}
