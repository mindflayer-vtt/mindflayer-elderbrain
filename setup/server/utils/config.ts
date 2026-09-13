import fs from "node:fs";
import path from "node:path";
import type { ApplianceConfig } from "../../shared/types";

export const defaults: ApplianceConfig = {
  version: 1,
  configured: false,
  domain: "elderbrain.local",
  views: [
    { output: "", url: "http://foundry.elderbrain.local", mode: "admin", tabs: [] },
    { output: "", url: "http://foundry.elderbrain.local", mode: "player", tabs: [] },
  ],
  controllers: {},
};

function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new Error("configuration must be an object");
  return value as Record<string, unknown>;
}

function browserUrl(value: unknown): string {
  if (typeof value !== "string" || value.length > 2048 || /[\x00-\x20\x7f]/.test(value)) throw new Error("invalid browser URL");
  const url = new URL(value);
  if (!["http:", "https:"].includes(url.protocol)) throw new Error("browser URLs must use HTTP(S)");
  if (url.username || url.password) throw new Error("browser URLs must not contain credentials");
  return url.href;
}

export function validate(value: unknown): ApplianceConfig {
  const input = record(value);
  const domain = String(input.domain || "")
    .trim()
    .toLowerCase();
  if (domain.length > 242 || !domain.split('.').every(label => /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(label)))
    throw new Error("invalid domain");
  if (!Array.isArray(input.views) || input.views.length < 1 || input.views.length > 2)
    throw new Error("one or two browser views are required");
  const views = input.views.map((value: unknown): ApplianceConfig['views'][number] => {
    const view = record(value);
    const output = String(view.output || "");
    if (output && !/^[A-Za-z0-9_.:-]{1,128}$/.test(output)) throw new Error("invalid display connector");
    const mode = view.mode ?? "player"; // Preserve old kiosk behavior for legacy configuration.
    if (mode !== "admin" && mode !== "player") throw new Error("invalid browser mode");
    const tabs = view.tabs ?? [];
    if (!Array.isArray(tabs) || tabs.length > 10) throw new Error("at most ten additional tabs are allowed");
    return { output, url: browserUrl(view.url), mode, tabs: tabs.map(browserUrl) };
  });
  const selected = views.map(view => view.output).filter(Boolean);
  if (new Set(selected).size !== selected.length) throw new Error("each display must have a distinct output");
  const controllers: ApplianceConfig["controllers"] = {};
  for (const [id, value] of Object.entries(record(input.controllers || {}))) {
    if (!/^[A-Za-z0-9._-]{1,64}$/.test(id))
      throw new Error("invalid controller ID");
    controllers[id] = { name: String(record(value).name || "").slice(0, 80) };
  }
  return {
    version: 1,
    configured: Boolean(input.configured),
    domain,
    views,
    controllers,
  };
}

export function load(file: string): ApplianceConfig {
  try {
    return {
      ...defaults,
      ...validate(JSON.parse(fs.readFileSync(file, "utf8"))),
    };
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return structuredClone(defaults);
    throw error;
  }
}

export function saveAtomic(file: string, value: unknown) {
  const valid = validate(value);
  fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  const temporary = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(temporary, `${JSON.stringify(valid, null, 2)}\n`, {
    mode: 0o600,
  });
  fs.renameSync(temporary, file);
  return valid;
}

export function saveFoundrySecret(file: string, value: unknown) {
  const values = record(value);
  const secret: Record<string, string> = {};
  try {
    const existing = record(JSON.parse(fs.readFileSync(file, "utf8")));
    if (typeof existing.foundry_admin_key === "string") secret.foundry_admin_key = existing.foundry_admin_key;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
  }
  if (values.releaseUrl) secret.foundry_release_url = String(values.releaseUrl);
  if (values.username) secret.foundry_username = String(values.username);
  if (values.password) secret.foundry_password = String(values.password);
  if (
    !secret.foundry_release_url &&
    !(secret.foundry_username && secret.foundry_password)
  )
    throw new Error("provide a timed URL or username and password");
  fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  const temporary = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(temporary, `${JSON.stringify(secret)}\n`, { mode: 0o600 });
  fs.renameSync(temporary, file);
}

export function removeFoundryDownloadSecret(file: string) {
  let existing: Record<string, unknown>;
  try { existing = record(JSON.parse(fs.readFileSync(file, "utf8"))); }
  catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return;
    throw error;
  }
  const key = existing.foundry_admin_key;
  if (typeof key !== "string") { fs.unlinkSync(file); return; }
  fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  const temporary = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(temporary, `${JSON.stringify({ foundry_admin_key: key })}\n`, { mode: 0o600 });
  fs.renameSync(temporary, file);
}
