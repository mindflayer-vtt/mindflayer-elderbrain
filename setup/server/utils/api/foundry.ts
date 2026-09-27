import path from "node:path";
import type { H3Event } from "h3";
import { command } from "../management";
import { saveFoundrySecret, removeFoundryDownloadSecret } from "../config";
import { beamerStatus, saveBeamer, removeBeamer } from "../beamer";
import { apiBody } from "../api-route";

export async function foundryApi(event: H3Event, route: string) {
  const method = event.method;
  const state = process.env.STATE_DIR || "/state";
  const secret = path.join(state, "secrets/foundry-config.json");
  const socket = process.env.MANAGEMENT_SOCKET || "/run/elderbrain/management.sock";
  const body = () => apiBody(event);
  if (route === "foundry/worlds" && method === "GET") {
    const result = await command(socket, "foundry-worlds");
    if (!result.ok) throw new Error("Foundry world discovery unavailable");
    return JSON.parse(result.output || "[]");
  }

  if (route === "foundry/beamer") {
    const file = path.join(state, "secrets/beamer.json");
    try {
      if (method === "GET") {
        const saved = beamerStatus(file);
        if (saved.state === "pairing-required") return { ...saved, views: [] };
        const result = await command(socket, "beamer-status");
        if (!result.ok) return { ...saved, state: "unavailable", views: [] };
        return { ...saved, ...JSON.parse(result.output || "{}") };
      }
      if (method === "PUT" || method === "DELETE") {
        const value = method === "PUT" ? saveBeamer(file, await body()) : removeBeamer(file);
        const refreshed = await command(socket, "beamer-refresh");
        if (!refreshed.ok) throw new Error("Beamer projection unavailable");
        return value;
      }
    } catch {
      // JSON parser exceptions may quote a malformed credential-bearing body.
      throw new Error("Unable to read or update Beamer configuration. Check the world ID, username and password requirements.");
    }
  }

  if (route === "foundry" && method === "PUT") {
    saveFoundrySecret(secret, await body());
    const administrator = await command(socket, "foundry-admin-key-ensure");
    if (!administrator.ok) throw new Error("Foundry administrator access could not be prepared");
    const started = await command(socket, "start-foundry").catch((e: Error) => ({ ok: false, error: e.message }));
    return { stored: true, started };
  }
  if (route === "foundry/admin-key" && method === "GET") {
    const result = await command(socket, "foundry-admin-key");
    if (!result.ok) throw new Error("Foundry administrator access is unavailable");
    return JSON.parse(result.output || "null");
  }
  if (route === "foundry/admin-key" && method === "POST") {
    const input = await body() as { confirmReset?: unknown };
    if (!input || Array.isArray(input) || Object.keys(input).join(",") !== "confirmReset" || input.confirmReset !== true)
      throw new Error("Confirm resetting the Foundry administrator access key");
    const result = await command(socket, "foundry-admin-key-reset", 45000);
    if (!result.ok) throw new Error("Foundry administrator access could not be reset");
    return JSON.parse(result.output || "null");
  }
  if (route === "foundry/credentials" && method === "DELETE") {
    removeFoundryDownloadSecret(secret);
    return { removed: true };
  }

  setResponseStatus(event, 404);
  return { error: "not found" };
}
