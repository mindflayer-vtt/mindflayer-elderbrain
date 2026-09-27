import path from "node:path";
import { command } from "./management-client";
import { saveFoundrySecret, removeFoundryDownloadSecret } from "./configuration";
import { beamerStatus, saveBeamer, removeBeamer } from "./beamer-config";

const state = () => process.env.STATE_DIR || "/state";
const socket = () => process.env.MANAGEMENT_SOCKET || "/run/elderbrain/management.sock";
const secret = () => path.join(state(), "secrets/foundry-config.json");
const beamerFile = () => path.join(state(), "secrets/beamer.json");

export async function worlds() {
  const result = await command(socket(), "foundry-worlds");
  if (!result.ok) throw new Error("Foundry world discovery unavailable");
  return JSON.parse(result.output || "[]");
}

export async function beamer() {
  try {
    const saved = beamerStatus(beamerFile());
    if (saved.state === "pairing-required") return { ...saved, views: [] };
    const result = await command(socket(), "beamer-status");
    if (!result.ok) return { ...saved, state: "unavailable", views: [] };
    return { ...saved, ...JSON.parse(result.output || "{}") };
  } catch {
    throw new Error("Unable to read or update Beamer configuration. Check the world ID, username and password requirements.");
  }
}

export async function configureBeamer(input: unknown) {
  try {
    const value = saveBeamer(beamerFile(), input);
    const refreshed = await command(socket(), "beamer-refresh");
    if (!refreshed.ok) throw new Error("Beamer projection unavailable");
    return value;
  } catch {
    throw new Error("Unable to read or update Beamer configuration. Check the world ID, username and password requirements.");
  }
}

export async function deleteBeamer() {
  try {
    const value = removeBeamer(beamerFile());
    const refreshed = await command(socket(), "beamer-refresh");
    if (!refreshed.ok) throw new Error("Beamer projection unavailable");
    return value;
  } catch {
    throw new Error("Unable to read or update Beamer configuration. Check the world ID, username and password requirements.");
  }
}

export async function configureFoundry(input: unknown) {
  saveFoundrySecret(secret(), input);
  const administrator = await command(socket(), "foundry-admin-key-ensure");
  if (!administrator.ok) throw new Error("Foundry administrator access could not be prepared");
  const started = await command(socket(), "start-foundry").catch((e: Error) => ({ ok: false, error: e.message }));
  return { stored: true, started };
}

export async function adminKey() {
  const result = await command(socket(), "foundry-admin-key");
  if (!result.ok) throw new Error("Foundry administrator access is unavailable");
  return JSON.parse(result.output || "null");
}

export async function resetAdminKey(input: unknown) {
  if (!input || typeof input !== "object" || Array.isArray(input) ||
      Object.keys(input).join(",") !== "confirmReset" ||
      (input as Record<string, unknown>).confirmReset !== true)
    throw new Error("Confirm resetting the Foundry administrator access key");
  const result = await command(socket(), "foundry-admin-key-reset", 45000);
  if (!result.ok) throw new Error("Foundry administrator access could not be reset");
  return JSON.parse(result.output || "null");
}

export function deleteCredentials() {
  removeFoundryDownloadSecret(secret());
  return { removed: true };
}
