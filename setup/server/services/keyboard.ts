import { command } from "./management-client";

export async function keyboardLayout(token: string, selected?: unknown, requireSelection = false) {
  if ((requireSelection || selected !== undefined) &&
      (typeof selected !== "string" || !/^[a-z0-9_-]{1,32}:[a-z0-9_-]{0,64}$/.test(selected)))
    throw new Error("Invalid keyboard layout");
  const result = await command(process.env.MANAGEMENT_SOCKET || "/run/elderbrain/management.sock",
    `kiosk-keyboard ${token}${selected === undefined ? "" : " " + selected}`);
  if (!result.ok) throw new Error("Local keyboard selection is unavailable");
  return JSON.parse(result.output || "{}");
}

export async function keyboardSettings(selected?: unknown) {
  if (selected !== undefined &&
      (typeof selected !== "string" || !/^[a-z0-9_-]{1,32}:[a-z0-9_-]{0,64}$/.test(selected)))
    throw new Error("Invalid keyboard layout");
  const result = await command(process.env.MANAGEMENT_SOCKET || "/run/elderbrain/management.sock",
    `keyboard-settings${selected === undefined ? "" : " " + selected}`);
  if (!result.ok) throw new Error("Unable to save keyboard layout");
  return JSON.parse(result.output || "{}");
}
