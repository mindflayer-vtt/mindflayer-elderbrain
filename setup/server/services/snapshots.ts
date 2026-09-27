import { randomBytes, createHash } from "node:crypto";
import { command } from "./management-client";

const socket = () => process.env.MANAGEMENT_SOCKET || "/run/elderbrain/management.sock";

export async function restoreNetwork(input: { checkpoint?: unknown; interface?: unknown; confirmRestore?: unknown; confirmDowntime?: unknown }) {
  if (input?.confirmRestore !== true || input.confirmDowntime !== true)
    throw new Error("Confirm network replacement and service downtime");
  if (typeof input.checkpoint !== "string" || !/^[a-f0-9]{32}$/.test(input.checkpoint) ||
      typeof input.interface !== "string" || !/^[A-Za-z0-9_.:-]{1,15}$/.test(input.interface))
    throw new Error("Choose a checkpoint and active network interface");
  const token = randomBytes(32).toString("base64url");
  const digest = createHash("sha256").update(token).digest("hex");
  const result = await command(socket(), `network-snapshot-restore-start ${input.checkpoint} ${input.interface} ${digest}`);
  if (!result.ok) throw new Error("Network restore was not accepted. Check active jobs and maintenance status.");
  // Only the initiator receives the capability; persistent jobs hold its hash.
  return { job: JSON.parse(result.output || "{}"), token };
}

export async function retention() {
  const result = await command(socket(), "snapshots-retention");
  if (!result.ok) throw new Error("Checkpoint retention settings unavailable");
  return JSON.parse(result.output || "{}");
}

export async function setRetention(input: { enabled?: unknown; keep?: unknown; confirmDeletion?: unknown }) {
  if (typeof input?.enabled !== "boolean" || typeof input.keep !== "number" || !Number.isInteger(input.keep) || input.keep < 1 || input.keep > 1000)
    throw new Error("Choose a checkpoint limit between 1 and 1000");
  if (input.enabled && input.confirmDeletion !== true) throw new Error("Confirm automatic deletion of older unprotected checkpoints");
  const result = await command(socket(), `snapshots-retention-set ${input.enabled} ${input.keep}`);
  if (!result.ok) throw new Error("Checkpoint retention settings unavailable");
  return JSON.parse(result.output || "{}");
}

export async function listSnapshots() {
  const result = await command(socket(), "snapshots-list");
  if (!result.ok) throw new Error("Local checkpoints require a healthy persistent Btrfs installation. Check maintenance status if unavailable.");
  return JSON.parse(result.output || "[]");
}

export async function restoreSnapshot(input: { checkpoint?: unknown; components?: unknown; confirmRestore?: unknown; confirmDowntime?: unknown }) {
  if (input?.confirmRestore !== true || input.confirmDowntime !== true) throw new Error("Confirm replacement of selected configuration and service downtime");
  if (typeof input.checkpoint !== "string" || !/^[a-f0-9]{32}$/.test(input.checkpoint) ||
      !Array.isArray(input.components) || !input.components.length ||
      input.components.some(value => typeof value !== "string" || !["preferences", "keypad-settings", "foundry"].includes(value)) ||
      new Set(input.components).size !== input.components.length)
    throw new Error("Choose a checkpoint and supported restore components");
  const result = await command(socket(), `snapshot-restore-start ${input.checkpoint} ${input.components.join(",")}`);
  if (!result.ok) throw new Error("Restore job was not accepted. Check active jobs before retrying.");
  return JSON.parse(result.output || "null");
}

async function startSnapshotJob(input: { confirmDowntime?: unknown }, action: "create" | "recover") {
  if (input?.confirmDowntime !== true) throw new Error("Confirm the temporary service interruption first");
  const result = await command(socket(), action === "create" ? "snapshot-create-start" : "snapshot-recover-start");
  if (!result.ok) throw new Error("Checkpoint job was not accepted. Check active jobs before retrying.");
  return JSON.parse(result.output || "null");
}

export const createSnapshot = (input: { confirmDowntime?: unknown }) => startSnapshotJob(input, "create");
export const recoverSnapshots = (input: { confirmDowntime?: unknown }) => startSnapshotJob(input, "recover");
