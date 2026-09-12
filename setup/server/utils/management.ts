import net from "node:net";
import { Readable, Transform } from "node:stream";
import { pipeline } from "node:stream/promises";
import type { ManagementResult } from "../../shared/types";

export function command(socketPath: string, action: string, timeout = 15000): Promise<ManagementResult> {
  return new Promise((resolve, reject) => {
    const socket = net.createConnection(socketPath);
    let output = "";
    socket.setTimeout(timeout);
    socket.on("connect", () => socket.end(`${action}\n`));
    socket.on("data", (chunk) => {
      output += chunk;
    });
    socket.on("end", () => {
      try {
        resolve(JSON.parse(output));
      } catch {
        reject(new Error("invalid management response"));
      }
    });
    socket.on("timeout", () => socket.destroy(new Error("management timeout")));
    socket.on("error", reject);
  });
}

export async function backupDownload(socketPath: string, id: string, operation: "backup-download" | "recovery-download" = "backup-download") {
  if (!/^[0-9a-f]{32}$/.test(id)) throw new Error("Invalid backup job ID");
  const socket = net.createConnection(socketPath);
  socket.setTimeout(30000, () => socket.destroy(new Error("Backup download timed out")));
  socket.on("connect", () => socket.end(`${operation} ${id}\n`));
  const iterator = socket[Symbol.asyncIterator]();
  let header = Buffer.alloc(0);
  try {
    while (true) {
      const next = await iterator.next();
      if (next.done) throw new Error("Incomplete download response");
      const chunk = Buffer.isBuffer(next.value) ? next.value : Buffer.from(next.value);
      const end = chunk.indexOf(10);
      if (end < 0) {
        header = Buffer.concat([header, chunk]);
        if (header.length > 4096) throw new Error("Invalid download response");
        continue;
      }
      if (header.length + end > 4096) throw new Error("Invalid download response");
      const metadata = JSON.parse(Buffer.concat([header, chunk.subarray(0, end)]).toString());
      if (!metadata.ok || !Number.isSafeInteger(metadata.size) || metadata.size < 0 || metadata.size > 1024 ** 4) {
        throw new Error("Backup is unavailable for download");
      }
      const initial = chunk.subarray(end + 1);
      const stream = Readable.from((async function* () {
        let received = initial.length;
        try {
          if (received > metadata.size) throw new Error("Invalid backup length");
          if (initial.length) yield initial;
          while (true) {
            const part = await iterator.next();
            if (part.done) break;
            received += part.value.length;
            if (received > metadata.size) throw new Error("Invalid backup length");
            yield part.value;
          }
          if (received !== metadata.size) throw new Error("Truncated backup download");
        } finally { socket.destroy(); }
      })());
      return { size: metadata.size as number, encrypted: metadata.encrypted === true, stream };
    }
  } catch (error) { socket.destroy(); throw error; }
}

export async function backupUpload(socketPath: string, input: Readable, size: number, operation: "backup-upload" | "backup-upload-encrypted" | "restore-preview-encrypted-start" | "borg-configure" | "backup-encrypted-start" | "keypad-install-start" | "display-preview-start" | "network-start" | "update-start" | "power-start" = "backup-upload"): Promise<ManagementResult> {
  if (!Number.isSafeInteger(size) || size <= 0 || size > 1024 ** 4) throw new Error("Invalid backup upload size");
  const socket = net.createConnection(socketPath);
  socket.setTimeout(30000, () => socket.destroy(new Error("Backup upload timed out")));
  let received = 0;
  const counter = new Transform({
    transform(chunk, _encoding, callback) {
      received += chunk.length;
      callback(received > size ? new Error("Backup upload exceeds declared size") : null, chunk);
    },
    flush(callback) { callback(received === size ? null : new Error("Truncated backup upload")); },
  });
  const response = new Promise<ManagementResult>((resolve, reject) => {
    let output = "";
    socket.on("data", chunk => {
      output += chunk.toString();
      if (output.length > 65536) socket.destroy(new Error("Invalid upload response"));
    });
    socket.on("error", reject);
    socket.on("end", () => {
      try { resolve(JSON.parse(output)); } catch { reject(new Error("Invalid upload response")); }
    });
  });
  socket.write(`${operation} ${size}\n`);
  const [, result] = await Promise.all([pipeline(input, counter, socket), response]);
  return result;
}
