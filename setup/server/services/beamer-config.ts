import fs from "node:fs";
import path from "node:path";
import { randomBytes } from "node:crypto";

export type BeamerCredential = { version: 1; revision: string; worldId: string; userId?: string; username?: string; password: string };

function fields(value: unknown) {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Invalid Beamer configuration");
  const input = value as Record<string, unknown>;
  const username = input.username === undefined && input.userId === undefined ? "Beamer" : input.username;
  const identity = username !== undefined
    ? { username: String(username) } : { userId: String(input.userId) };
  if (typeof input.worldId !== "string" || !/^[A-Za-z0-9_-]{1,128}$/.test(input.worldId)
    || (username !== undefined
      ? typeof username !== "string" || !username.trim() || username.length > 128 || /[\x00-\x1f\x7f]/.test(username)
      : typeof input.userId !== "string" || !/^[A-Za-z0-9]{16}$/.test(input.userId))
    || typeof input.password !== "string" || input.password.length < 12 || input.password.length > 256
    || /[\x00-\x1f\x7f]/.test(input.password)) throw new Error("Enter a world ID, a username and a password of 12–256 characters");
  return { worldId: input.worldId, ...identity, password: input.password };
}

/** Private local credentials only: callers must not serialize this record to clients. */
export function readBeamer(file: string): BeamerCredential | null {
  let fd;
  try {
    fd = fs.openSync(file, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW);
    const stat = fs.fstatSync(fd);
    if (!stat.isFile() || stat.size > 4096 || (stat.mode & 0o077)) throw new Error("Unsafe credential file");
    const value = JSON.parse(fs.readFileSync(fd, "utf8"));
    if (value.version !== 1 || !/^[a-f0-9]{32}$/.test(value.revision)) throw new Error("Invalid credential record");
    return { version: 1, revision: value.revision, ...fields(value) };
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw new Error("Stored Beamer configuration is unavailable");
  } finally { if (fd !== undefined) fs.closeSync(fd); }
}

export function beamerStatus(file: string) {
  const credential = readBeamer(file);
  return credential ? { state: "pending-verification" as const, worldId: credential.worldId, username: credential.username ?? "", userId: credential.userId }
    : { state: "pairing-required" as const, worldId: "", username: "Beamer", userId: undefined };
}

export function saveBeamer(file: string, input: unknown) {
  const value: BeamerCredential = { version: 1, revision: randomBytes(16).toString("hex"), ...fields(input) };
  fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  const temporary = `${file}.${value.revision}.tmp`;
  let fd;
  try {
    fd = fs.openSync(temporary, fs.constants.O_WRONLY | fs.constants.O_CREAT | fs.constants.O_EXCL | fs.constants.O_NOFOLLOW, 0o600);
    fs.writeFileSync(fd, JSON.stringify(value) + "\n");
    fs.fsyncSync(fd);
    fs.closeSync(fd); fd = undefined;
    fs.renameSync(temporary, file);
    const directory = fs.openSync(path.dirname(file), fs.constants.O_RDONLY);
    try { fs.fsyncSync(directory); } finally { fs.closeSync(directory); }
  } finally {
    if (fd !== undefined) fs.closeSync(fd);
    try { fs.unlinkSync(temporary); } catch (error) { if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error; }
  }
  return beamerStatus(file);
}

export function removeBeamer(file: string) {
  try { fs.unlinkSync(file); } catch (error) { if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error; }
  return beamerStatus(file);
}
