import { Readable } from "node:stream";
import { command, backupDownload, backupUpload } from "./management-client";

const socket = () => process.env.MANAGEMENT_SOCKET || "/run/elderbrain/management.sock";

export function downloadRecoveryKit(id: string) {
  if (!/^[0-9a-f]{32}$/.test(id)) return null;
  return backupDownload(socket(), id, "recovery-download");
}

export async function borgSettings() {
  const result = await command(socket(), "borg-settings");
  if (!result.ok) throw new Error(result.error || "Borg settings unavailable");
  return JSON.parse(result.output || "null");
}

export async function configureBorg(input: unknown) {
  const data = Buffer.from(JSON.stringify(input));
  const result = await backupUpload(socket(), Readable.from([data]), data.length, "borg-configure");
  if (!result.ok) throw new Error(result.error || "Borg settings unavailable");
  return JSON.parse(result.output || "null");
}

async function startBorgOperation(action: "init" | "test" | "list" | "backup" | "fetch" | "recovery-kit", input: { confirm?: boolean; archive?: string }) {
  if (["init", "recovery-kit"].includes(action) && input.confirm !== true)
    throw new Error("This repository operation requires explicit confirmation");
  if (action === "fetch" && (typeof input.archive !== "string" || !/^elderbrain-[A-Za-z0-9_.:+-]{1,200}$/.test(input.archive)))
    throw new Error("Invalid archive name");
  const result = await command(socket(), `borg-${action}-start` + (action === "fetch" ? " " + input.archive : ""));
  if (!result.ok) throw new Error(result.error || "Borg operation unavailable");
  return JSON.parse(result.output || "null");
}

export const initBorg = (input: { confirm?: boolean }) => startBorgOperation("init", input);
export const testBorg = (input: object) => startBorgOperation("test", input);
export const listBorg = (input: object) => startBorgOperation("list", input);
export const backupBorg = (input: object) => startBorgOperation("backup", input);
export const fetchBorg = (input: { archive?: string }) => startBorgOperation("fetch", input);
export const createRecoveryKit = (input: { confirm?: boolean }) => startBorgOperation("recovery-kit", input);
