import { Readable } from "node:stream";
import { command, backupUpload } from "./management-client";
import { updateRequest } from "./update-request";

const socket = () => process.env.MANAGEMENT_SOCKET || "/run/elderbrain/management.sock";

export async function releaseStatus() {
  const result = await command(socket(), "release-status");
  if (!result.ok) throw new Error("Installed release status unavailable");
  return JSON.parse(result.output || "null");
}

export async function powerStatus() {
  const result = await command(socket(), "power-status");
  if (!result.ok) throw new Error("Power status unavailable");
  return JSON.parse(result.output || "null");
}

export async function requestPower(input: unknown) {
  if (!input || typeof input !== "object" || Array.isArray(input) ||
      Object.keys(input).sort().join(",") !== "action,confirmPower" ||
      !["reboot", "shutdown"].includes((input as Record<string, unknown>).action as string) ||
      (input as Record<string, unknown>).confirmPower !== true)
    throw new Error("Choose reboot or shutdown and explicitly confirm service interruption");
  const payload = Buffer.from(JSON.stringify(input));
  const result = await backupUpload(socket(), Readable.from([payload]), payload.length, "power-start");
  if (!result.ok) throw new Error("Power request was not accepted. Check active jobs and maintenance status.");
  return JSON.parse(result.output || "null");
}

export async function checkRelease(input: unknown) {
  if (!input || typeof input !== "object" || Array.isArray(input) || Object.keys(input).length)
    throw new Error("Release checks do not accept a custom source or key");
  const result = await command(socket(), "release-check", 35000);
  if (!result.ok) throw new Error("Release check failed. Check the configured source, signing key and network connection.");
  return JSON.parse(result.output || "null");
}

export async function startUpdate(input: unknown) {
  const payload = Buffer.from(JSON.stringify(updateRequest(input)));
  const result = await backupUpload(socket(), Readable.from([payload]), payload.length, "update-start");
  if (!result.ok) throw new Error("Update was not accepted. Check active jobs and maintenance status before retrying.");
  return JSON.parse(result.output || "null");
}
