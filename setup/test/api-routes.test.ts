import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const api = path.resolve(import.meta.dirname, "../server/routes/elderbrain/api");
const legacy = path.resolve(import.meta.dirname, "../server/api");

test("administration API uses explicit Nitro route files", () => {
  const routes = [
    "system/release.ts", "system/power.ts", "system/check.ts",
    "system/update.ts", "snapshots/index.ts", "snapshots/recover.ts",
    "snapshots/restore.ts", "snapshots/restore-network.ts", "snapshots/retention.ts",
    "foundry/worlds.ts", "foundry/beamer.ts", "foundry/index.ts",
    "foundry/admin-key.ts", "foundry/credentials.ts", "network/index.ts",
    "network/change.ts", "network/change/cancel.ts", "display-preview/index.ts",
    "display-preview/confirm.ts", "display-preview/cancel.ts", "displays.ts",
    "borg/settings.ts", "borg/recovery-kits/[id]/download.ts", "borg/init.ts",
    "borg/test.ts", "borg/list.ts", "borg/backup.ts",
    "borg/fetch.ts", "borg/recovery-kit.ts", "backups/index.ts",
    "backups/upload.ts", "backups/upload-encrypted.ts", "backups/preview-encrypted.ts",
    "backups/[id]/restore.ts", "backups/[id]/download.ts", "jobs.ts",
    "keypads/index.ts", "keypads/[id].ts", "keypads/release.ts",
    "keypads/install.ts", "keypads/provision.ts", "keypads/usb.ts",
    "keypad-settings.ts", "logs/foundry.ts", "logs/foundry/download.ts",
    "config.ts", "controllers.ts", "controllers/[id]/identify.ts",
    "status.ts", "actions/restart-foundry.ts", "actions/restart-mindflayer.ts",
    "actions/restart-browser-session.ts",
  ];
  const fallback = path.join(api, "[...path].ts");
  const legacyRoutes = fs.existsSync(legacy) ? fs.readdirSync(legacy, { recursive: true }).filter(value => String(value).endsWith(".ts")) : [];
  assert.deepEqual(legacyRoutes, [], "API handlers must only be mounted under /elderbrain/api");
  assert.equal(fs.existsSync(fallback), true, "unknown API paths need a 404 route");
  assert.match(fs.readFileSync(fallback, "utf8"), /setResponseStatus\(event, 404\)/);
  for (const route of routes) {
    assert.equal(fs.existsSync(path.join(api, route)) && fs.statSync(path.join(api, route)).isFile(), true, route);
    assert.match(fs.readFileSync(path.join(api, route), "utf8"), /apiRoute\(event =>/);
  }
});
