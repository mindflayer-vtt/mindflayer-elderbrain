import { Readable } from "node:stream";
import { command, backupUpload } from "./management-client";
import { validate } from "./configuration";

const socket = () => process.env.MANAGEMENT_SOCKET || "/run/elderbrain/management.sock";

export async function previewStatus() {
  const result = await command(socket(), "display-preview-status");
  if (!result.ok) throw new Error("Display preview status unavailable");
  return JSON.parse(result.output || "{}");
}

export async function startPreview(input: unknown) {
  const candidate = Buffer.from(JSON.stringify(validate(input)));
  const result = await backupUpload(socket(), Readable.from([candidate]), candidate.length, "display-preview-start");
  if (!result.ok) throw new Error("Unable to start display preview. Check its status before retrying.");
  return JSON.parse(result.output || "{}");
}

async function resolvePreview(input: { id?: unknown }, action: "confirm" | "cancel") {
  if (typeof input.id !== "string" || !/^[a-f0-9]{32}$/.test(input.id)) throw new Error("Invalid display preview ID");
  const result = await command(socket(), `display-preview-${action} ${input.id}`);
  if (!result.ok) throw new Error("Preview is no longer pending, expired, or could not be updated. Refresh its status.");
  return JSON.parse(result.output || "{}");
}

export const confirmPreview = (input: { id?: unknown }) => resolvePreview(input, "confirm");
export const cancelPreview = (input: { id?: unknown }) => resolvePreview(input, "cancel");

export async function hostDisplays() {
  const result = await command(socket(), "host-displays");
  if (!result.ok) throw new Error("Host display discovery unavailable");
  return JSON.parse(result.output || "{}");
}
