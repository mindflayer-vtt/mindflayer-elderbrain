import { Readable } from "node:stream";
import type { H3Event } from "h3";
import { command, backupDownload, backupUpload } from "../management";
import { apiBody } from "../api-route";

export async function backupsApi(event: H3Event, route: string) {
  const method = event.method;
  const socket = process.env.MANAGEMENT_SOCKET || "/run/elderbrain/management.sock";
  const body = () => apiBody(event);
  if (["backups/upload", "backups/upload-encrypted"].includes(route) && method === "POST") {
    const size = Number(getHeader(event, "content-length"));
    if (!Number.isSafeInteger(size) || size <= 0 || size > 1024 ** 4) {
      setResponseStatus(event, 411);
      return { error: "A positive Content-Length up to 1 TiB is required" };
    }
    const result = await backupUpload(socket, event.node.req, size, route.endsWith("-encrypted") ? "backup-upload-encrypted" : "backup-upload");
    if (!result.ok) throw new Error(result.error || "Upload rejected");
    setResponseStatus(event, 202);
    return JSON.parse(result.output || "null");
  }
  if (route === "backups/preview-encrypted" && method === "POST") {
    const input = await body() as { uploadId?: string; passphrase?: string };
    if (typeof input.uploadId !== "string" || !/^[0-9a-f]{32}$/.test(input.uploadId)) throw new Error("Invalid upload identity");
    if (typeof input.passphrase !== "string" || input.passphrase.length < 12 || input.passphrase.length > 1024 || /[\r\n\0]/.test(input.passphrase)) throw new Error("Invalid decryption passphrase");
    const payload = Buffer.from(JSON.stringify({ uploadId: input.uploadId, passphrase: input.passphrase }));
    const result = await backupUpload(socket, Readable.from([payload]), payload.length, "restore-preview-encrypted-start");
    if (!result.ok) throw new Error(result.error || "Encrypted preview unavailable");
    setResponseStatus(event, 202);
    return JSON.parse(result.output || "null");
  }
  const restore = /^backups\/([0-9a-f]{32})\/restore$/.exec(route);
  if (restore && method === "POST") {
    const input = await body() as { confirm?: boolean };
    if (input.confirm !== true) throw new Error("Explicit restore confirmation is required");
    const result = await command(socket, "restore-start " + restore[1]);
    if (!result.ok) throw new Error(result.error || "Restore rejected");
    setResponseStatus(event, 202);
    return JSON.parse(result.output || "null");
  }
  const download = /^backups\/([0-9a-f]{32})\/download$/.exec(route);
  if (download && method === "GET") {
    const result = await backupDownload(socket, download[1]!);
    setHeader(event, "content-type", result.encrypted ? "application/octet-stream" : "application/zstd");
    setHeader(event, "content-length", result.size);
    setHeader(event, "content-disposition", `attachment; filename="elderbrain-${download[1]}.tar.zst${result.encrypted ? '.gpg' : ''}"`);
    return sendStream(event, result.stream);
  }
  if ((route === "jobs" && method === "GET") || (route === "backups" && method === "POST")) {
    const input = method === "POST" ? await body() as { encrypt?: boolean; passphrase?: string } : {};
    if (input.encrypt && (typeof input.passphrase !== "string" || input.passphrase.length < 12 || input.passphrase.length > 1024)) throw new Error("Encryption passphrase must be 12–1024 characters");
    const payload = input.encrypt ? Buffer.from(JSON.stringify({ passphrase: input.passphrase })) : undefined;
    const result = payload ? await backupUpload(socket, Readable.from([payload]), payload.length, "backup-encrypted-start")
      : await command(socket, route === "jobs" ? "jobs-list" : "backup-start");
    if (!result.ok) {
      setResponseStatus(event, 503);
      return { error: result.error || "Host jobs unavailable" };
    }
    if (method === "POST") setResponseStatus(event, 202);
    return JSON.parse(result.output || "null");
  }

  setResponseStatus(event, 404);
  return { error: "not found" };
}
