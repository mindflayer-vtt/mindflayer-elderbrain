import { Readable } from "node:stream";
import { command, backupDownload, backupUpload } from "./management-client";

const socket = () => process.env.MANAGEMENT_SOCKET || "/run/elderbrain/management.sock";
const validId = (id: string) => /^[0-9a-f]{32}$/.test(id);

export async function uploadBackup(stream: Readable, size: number, encrypted: boolean) {
  const result = await backupUpload(socket(), stream, size, encrypted ? "backup-upload-encrypted" : "backup-upload");
  if (!result.ok) throw new Error(result.error || "Upload rejected");
  return JSON.parse(result.output || "null");
}

export async function previewEncryptedBackup(input: { uploadId?: string; passphrase?: string }) {
  if (typeof input.uploadId !== "string" || !validId(input.uploadId)) throw new Error("Invalid upload identity");
  if (typeof input.passphrase !== "string" || input.passphrase.length < 12 || input.passphrase.length > 1024 || /[\r\n\0]/.test(input.passphrase))
    throw new Error("Invalid decryption passphrase");
  const payload = Buffer.from(JSON.stringify({ uploadId: input.uploadId, passphrase: input.passphrase }));
  const result = await backupUpload(socket(), Readable.from([payload]), payload.length, "restore-preview-encrypted-start");
  if (!result.ok) throw new Error(result.error || "Encrypted preview unavailable");
  return JSON.parse(result.output || "null");
}

export async function restoreBackup(id: string, input: { confirm?: boolean }) {
  if (!validId(id)) return null;
  if (input.confirm !== true) throw new Error("Explicit restore confirmation is required");
  const result = await command(socket(), "restore-start " + id);
  if (!result.ok) throw new Error(result.error || "Restore rejected");
  return JSON.parse(result.output || "null");
}

export function downloadBackup(id: string) {
  if (!validId(id)) return null;
  return backupDownload(socket(), id);
}

export function jobs() { return command(socket(), "jobs-list"); }

export async function startBackup(input: { encrypt?: boolean; passphrase?: string }) {
  if (input.encrypt && (typeof input.passphrase !== "string" || input.passphrase.length < 12 || input.passphrase.length > 1024))
    throw new Error("Encryption passphrase must be 12–1024 characters");
  const payload = input.encrypt ? Buffer.from(JSON.stringify({ passphrase: input.passphrase })) : undefined;
  return payload ? backupUpload(socket(), Readable.from([payload]), payload.length, "backup-encrypted-start")
    : command(socket(), "backup-start");
}
