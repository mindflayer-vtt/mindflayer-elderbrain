import fs from "node:fs";
import { randomBytes, createHash } from 'node:crypto';
import path from "node:path";
import { Readable } from "node:stream";
import { command, backupDownload, backupUpload } from "../utils/management";
import { load, validate, saveFoundrySecret } from "../utils/config";
import { beamerStatus, saveBeamer, removeBeamer } from "../utils/beamer";
import { updateRequest } from '../utils/update-request';
import type { ControllerMonitor } from "../utils/controllers";
import type { KeypadInventory } from "../utils/keypads";

export default defineEventHandler(async (event) => {
  setHeader(event, "cache-control", "no-store");
  const route = getRouterParam(event, "path") || "";
  const method = event.method;
  const state = process.env.STATE_DIR || "/state";
  const config = path.join(state, "config.json");
  const secret = path.join(state, "secrets/foundry-config.json");
  const socket = process.env.MANAGEMENT_SOCKET || "/run/elderbrain/management.sock";
  const monitor = event.context.monitor as ControllerMonitor;
  async function body() {
    let size = 0;
    const chunks: Buffer[] = [];
    for await (const chunk of event.node.req) {
      const bytes = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
      size += bytes.length;
      if (size <= 65536) chunks.push(bytes);
    }
    if (size > 65536) throw new Error("request too large");
    return JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}") as unknown;
  }
  try {
    if (route === 'system/power' && method === 'GET') {
      const result = await command(socket, 'power-status');
      if (!result.ok) throw new Error('Power status unavailable');
      return JSON.parse(result.output || 'null');
    }
    if (route === 'system/power' && method === 'POST') {
      const input = await body() as Record<string, unknown>;
      if (!input || Array.isArray(input) || Object.keys(input).sort().join(',') !== 'action,confirmPower'
          || !['reboot', 'shutdown'].includes(input.action as string) || input.confirmPower !== true)
        throw new Error('Choose reboot or shutdown and explicitly confirm service interruption');
      const payload = Buffer.from(JSON.stringify(input));
      const result = await backupUpload(socket, Readable.from([payload]), payload.length, 'power-start');
      if (!result.ok) throw new Error('Power request was not accepted. Check active jobs and maintenance status.');
      setResponseStatus(event, 202);
      return JSON.parse(result.output || 'null');
    }
    if (route === 'system/check' && method === 'POST') {
      const input = await body();
      if (!input || typeof input !== 'object' || Array.isArray(input) || Object.keys(input).length)
        throw new Error('Release checks do not accept a custom source or key');
      const result = await command(socket, 'release-check', 35000);
      if (!result.ok) throw new Error('Release check failed. Check the configured source, signing key and network connection.');
      return JSON.parse(result.output || 'null');
    }
    if (route === 'system/update' && method === 'POST') {
      const payload = Buffer.from(JSON.stringify(updateRequest(await body())));
      const result = await backupUpload(socket, Readable.from([payload]), payload.length, 'update-start');
      if (!result.ok) throw new Error('Update was not accepted. Check active jobs and maintenance status before retrying.');
      setResponseStatus(event, 202);
      return JSON.parse(result.output || 'null');
    }
    if (route === 'snapshots/restore-network' && method === 'POST') {
      const input = await body() as { checkpoint?: unknown; interface?: unknown; confirmRestore?: unknown; confirmDowntime?: unknown };
      if (input?.confirmRestore !== true || input.confirmDowntime !== true)
        throw new Error('Confirm network replacement and service downtime');
      if (typeof input.checkpoint !== 'string' || !/^[a-f0-9]{32}$/.test(input.checkpoint)
          || typeof input.interface !== 'string' || !/^[A-Za-z0-9_.:-]{1,15}$/.test(input.interface))
        throw new Error('Choose a checkpoint and active network interface');
      const token = randomBytes(32).toString('base64url');
      const digest = createHash('sha256').update(token).digest('hex');
      const result = await command(socket, `network-snapshot-restore-start ${input.checkpoint} ${input.interface} ${digest}`);
      if (!result.ok) throw new Error('Network restore was not accepted. Check active jobs and maintenance status.');
      // Only the initiator receives the capability. Persistent jobs hold its
      // hash and return the network transaction ID after service resumption.
      return { job: JSON.parse(result.output || '{}'), token };
    }
    if (route === 'snapshots/retention' && ['GET', 'PUT'].includes(method)) {
      let action = 'snapshots-retention';
      if (method === 'PUT') {
        const input = await body() as { enabled?: unknown; keep?: unknown; confirmDeletion?: unknown };
        if (typeof input?.enabled !== 'boolean' || typeof input.keep !== 'number' || !Number.isInteger(input.keep) || input.keep < 1 || input.keep > 1000)
          throw new Error('Choose a checkpoint limit between 1 and 1000');
        if (input.enabled && input.confirmDeletion !== true) throw new Error('Confirm automatic deletion of older unprotected checkpoints');
        action = `snapshots-retention-set ${input.enabled} ${input.keep}`;
      }
      const result = await command(socket, action);
      if (!result.ok) throw new Error('Checkpoint retention settings unavailable');
      return JSON.parse(result.output || '{}');
    }
    if (route === "snapshots" && method === "GET") {
      const result = await command(socket, "snapshots-list");
      if (!result.ok) throw new Error("Local checkpoints require a healthy persistent Btrfs installation. Check maintenance status if unavailable.");
      return JSON.parse(result.output || "[]");
    }
    if (route === 'snapshots/restore' && method === 'POST') {
      const input = await body() as { checkpoint?: unknown; components?: unknown; confirmRestore?: unknown; confirmDowntime?: unknown };
      if (input?.confirmRestore !== true || input.confirmDowntime !== true) throw new Error('Confirm replacement of selected configuration and service downtime');
      if (typeof input.checkpoint !== 'string' || !/^[a-f0-9]{32}$/.test(input.checkpoint)
          || !Array.isArray(input.components) || !input.components.length
          || input.components.some(value => typeof value !== 'string' || !['preferences', 'keypad-settings', 'foundry'].includes(value))
          || new Set(input.components).size !== input.components.length) throw new Error('Choose a checkpoint and supported restore components');
      const result = await command(socket, `snapshot-restore-start ${input.checkpoint} ${input.components.join(',')}`);
      if (!result.ok) throw new Error('Restore job was not accepted. Check active jobs before retrying.');
      setResponseStatus(event, 202);
      return JSON.parse(result.output || 'null');
    }
    if (["snapshots", "snapshots/recover"].includes(route) && method === "POST") {
      const input = await body() as { confirmDowntime?: unknown };
      if (input?.confirmDowntime !== true) throw new Error("Confirm the temporary service interruption first");
      const result = await command(socket, route === "snapshots" ? "snapshot-create-start" : "snapshot-recover-start");
      if (!result.ok) throw new Error("Checkpoint job was not accepted. Check active jobs before retrying.");
      setResponseStatus(event, 202);
      return JSON.parse(result.output || "null");
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
    if (route === "network/change" && method === "GET") {
      const result = await command(socket, "network-status");
      if (!result.ok) throw new Error("Network change status unavailable");
      return JSON.parse(result.output || "{}");
    }
    if (route === "network/change" && method === "POST") {
      const candidate = Buffer.from(JSON.stringify(await body()));
      if (candidate.length > 2048) throw new Error("Network settings are too large");
      const result = await backupUpload(socket, Readable.from([candidate]), candidate.length, "network-start");
      if (!result.ok) throw new Error("Unable to stage network changes. Check status before retrying.");
      setResponseStatus(event, 202);
      return JSON.parse(result.output || "{}");
    }
    if (route === "network/change/cancel" && method === "POST") {
      const input = await body() as { id?: unknown };
      if (typeof input?.id !== "string" || !/^[a-f0-9]{32}$/.test(input.id)) throw new Error("Invalid network change ID");
      const result = await command(socket, "network-cancel " + input.id);
      if (!result.ok) throw new Error("Network change could not be reverted. Refresh its status.");
      return JSON.parse(result.output || "{}");
    }
    if (route === "display-preview" && method === "GET") {
      const result = await command(socket, "display-preview-status");
      if (!result.ok) throw new Error("Display preview status unavailable");
      return JSON.parse(result.output || "{}");
    }
    if (route === "display-preview" && method === "POST") {
      const candidate = Buffer.from(JSON.stringify(validate(await body())));
      const result = await backupUpload(socket, Readable.from([candidate]), candidate.length, "display-preview-start");
      if (!result.ok) throw new Error("Unable to start display preview. Check its status before retrying.");
      setResponseStatus(event, 202);
      return JSON.parse(result.output || "{}");
    }
    if (["display-preview/confirm", "display-preview/cancel"].includes(route) && method === "POST") {
      const input = await body() as { id?: unknown };
      if (typeof input.id !== "string" || !/^[a-f0-9]{32}$/.test(input.id)) throw new Error("Invalid display preview ID");
      const result = await command(socket, route.endsWith("/confirm") ? "display-preview-confirm " + input.id : "display-preview-cancel " + input.id);
      if (!result.ok) throw new Error("Preview is no longer pending, expired, or could not be updated. Refresh its status.");
      return JSON.parse(result.output || "{}");
    }
    if (route === "displays" && method === "GET") {
      const result = await command(socket, "host-displays");
      if (!result.ok) throw new Error("Host display discovery unavailable");
      return JSON.parse(result.output || "{}");
    }
    if (route === "network" && method === "GET") {
      const result = await command(socket, "host-network");
      if (!result.ok) throw new Error("Host network discovery unavailable");
      return JSON.parse(result.output || "{}");
    }
    const kit = /^borg\/recovery-kits\/([0-9a-f]{32})\/download$/.exec(route);
    if (kit && method === "GET") {
      const result = await backupDownload(socket, kit[1]!, "recovery-download");
      setHeader(event, "content-type", "application/json");
      setHeader(event, "content-length", result.size);
      setHeader(event, "content-disposition", `attachment; filename="elderbrain-recovery-${kit[1]}.json"`);
      return sendStream(event, result.stream);
    }
    if (route === "borg/settings" && ["GET", "PUT"].includes(method)) {
      const data = method === "PUT" ? Buffer.from(JSON.stringify(await body())) : undefined;
      const result = data ? await backupUpload(socket, Readable.from([data]), data.length, "borg-configure") : await command(socket, "borg-settings");
      if (!result.ok) throw new Error(result.error || "Borg settings unavailable");
      return JSON.parse(result.output || "null");
    }
    const borgAction = /^borg\/(init|test|list|backup|fetch|recovery-kit)$/.exec(route);
    if (borgAction && method === "POST") {
      const input = await body() as { confirm?: boolean; archive?: string };
      if (["init", "recovery-kit"].includes(borgAction[1]!) && input.confirm !== true) throw new Error("This repository operation requires explicit confirmation");
      if (borgAction[1] === "fetch" && (typeof input.archive !== "string" || !/^elderbrain-[A-Za-z0-9_.:+-]{1,200}$/.test(input.archive))) throw new Error("Invalid archive name");
      const result = await command(socket, `borg-${borgAction[1]}-start` + (borgAction[1] === "fetch" ? " " + input.archive : ""));
      if (!result.ok) throw new Error(result.error || "Borg operation unavailable");
      setResponseStatus(event, 202);
      return JSON.parse(result.output || "null");
    }
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
    const inventory = event.context.inventory as KeypadInventory;
    if (route === "keypads/release" && method === "GET") {
      const result = await command(socket, "keypad-release", 180000);
      if (!result.ok) throw new Error("No installable stable release is available, or GitHub could not be reached. A signed serial-install bundle is required; OTA firmware alone is insufficient.");
      return JSON.parse(result.output || "null");
    }
    if (route === "keypads/install" && method === "POST") {
      const input = await body() as Record<string, unknown>;
      if (!input || input.confirm !== true || typeof input.usbId !== "string" || !/^[a-f0-9]{32}$/.test(input.usbId) ||
          typeof input.version !== "string" || !/^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$/.test(input.version) ||
          !Number.isSafeInteger(input.revision) || Number(input.revision) < 1 || typeof input.adopt !== "boolean") throw new Error("Confirm the USB target, firmware release and saved settings before installation");
      const payload = Buffer.from(JSON.stringify({ usbId: input.usbId, version: input.version, revision: input.revision, adopt: input.adopt }));
      const result = await backupUpload(socket, Readable.from([payload]), payload.length, "keypad-install-start");
      if (!result.ok) throw new Error("Installation could not start. Check saved settings, active host jobs and USB connection, then refresh.");
      setResponseStatus(event, 202);
      return JSON.parse(result.output || "null");
    }
    if (route === "keypads/usb" && method === "GET") {
      const result = await command(socket, "keypad-usb-devices");
      if (!result.ok) throw new Error("USB discovery unavailable");
      return JSON.parse(result.output || "null");
    }
    if (route === "keypads" && method === "GET") {
      try {
        const result = await command(socket, "keypad-registrations");
        if (!result.ok) throw new Error("Registrations unavailable");
        inventory.registrations(JSON.parse(result.output || "null"));
        setHeader(event, "x-elderbrain-inventory-source", "current");
      } catch {
        inventory.registrationsUnavailable();
        setHeader(event, "x-elderbrain-inventory-source", "unavailable");
      }
      try {
        const receipts = await command(socket, "keypad-installations");
        if (!receipts.ok) throw new Error("Installation receipts unavailable");
        inventory.installationReceipts(JSON.parse(receipts.output || "null"));
        setHeader(event, "x-elderbrain-installation-source", "current");
      } catch { setHeader(event, "x-elderbrain-installation-source", "unavailable"); }
      return inventory.list();
    }
    if (route === "keypad-settings" && method === "GET") return inventory.publicSettings();
    if (route === "keypad-settings" && method === "PUT") return inventory.configure(await body() as Record<string, unknown>);
    const keypad = /^keypads\/([A-Za-z0-9._-]{1,64})$/.exec(route);
    if (keypad && method === "PUT") {
      const input = await body() as Record<string, unknown>;
      const record = inventory.rename(keypad[1]!, input);
      let ledDelivery: "sent" | "pending" | "disabled" = record.ledPreferences ? "pending" : "disabled";
      if (input.ledPreferences !== undefined && record.ledPreferences) {
        try { monitor.configureLeds(record.id, record.ledPreferences); ledDelivery = "sent"; } catch {}
      }
      return { ...record, ledDelivery };
    }
    if ((route === "logs/foundry" || route === "logs/foundry/download") && method === "GET") {
      const result = await command(socket, "foundry-logs");
      if (!result.ok) {
        setResponseStatus(event, 503);
        return { error: result.error || "Unable to read Foundry logs" };
      }
      if (route.endsWith("/download")) {
        setHeader(event, "content-type", "text/plain; charset=utf-8");
        setHeader(event, "content-disposition", 'attachment; filename="foundry-recent.log"');
        return result.output || "";
      }
      return { output: result.output || "", updatedAt: new Date().toISOString() };
    }
    if (route === "config" && method === "GET") return load(config);
    if (route === "config" && method === "PUT") {
      setResponseStatus(event, 409);
      return { error: "Configuration changes require a display preview and explicit confirmation" };
    }
    if (route === "foundry" && method === "PUT") {
      saveFoundrySecret(secret, await body());
      const started = await command(socket, "start-foundry").catch((e: Error) => ({ ok: false, error: e.message }));
      return { stored: true, started };
    }
    if (route === "foundry/credentials" && method === "DELETE") {
      try { fs.unlinkSync(secret); } catch (e) { if ((e as NodeJS.ErrnoException).code !== "ENOENT") throw e; }
      return { removed: true };
    }
    if (route === "controllers" && method === "GET") return monitor.snapshot();
    const identify = /^controllers\/([^/]+)\/identify$/.exec(route);
    if (identify && method === "POST") { monitor.identify(decodeURIComponent(identify[1]!)); return { sent: true }; }
    if (route === "status" && method === "GET") {
      let version = "development";
      try { version = fs.readFileSync(process.env.APPLIANCE_VERSION_FILE || "/opt/elderbrain/VERSION", "utf8").trim(); } catch {}
      const managed = await command(socket, "host-metrics");
      if (!managed.ok) throw new Error("Host metrics unavailable");
      return { version, mindflayerServerImage: process.env.MINDFLAYER_SERVER_IMAGE || "unknown",
        ...JSON.parse(managed.output || "{}") };
    }
    const action = /^actions\/(restart-foundry|restart-mindflayer|restart-browser-session)$/.exec(route);
    if (action && method === "POST") return await command(socket, action[1]!);
    setResponseStatus(event, 404);
    return { error: "not found" };
  } catch (e) {
    setResponseStatus(event, 400);
    return { error: e instanceof Error ? e.message : "request failed" };
  }
});
