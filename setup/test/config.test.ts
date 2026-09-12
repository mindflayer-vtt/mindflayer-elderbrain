import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  defaults,
  load,
  saveAtomic,
  saveFoundrySecret,
  validate,
} from "../server/utils/config.ts";

test("defaults represent an unconfigured two-view appliance", () => {
  assert.equal(defaults.configured, false);
  assert.equal(defaults.views.length, 2);
});
test("browser modes support one screen, legacy kiosks, and bounded safe tabs", () => {
  const legacy = validate({ ...defaults, views: [{ output: "DP-1", url: "https://foundry.example" }] });
  assert.equal(legacy.views[0]?.mode, "player");
  const admin = { output: "DP-1", url: "https://foundry.example", mode: "admin", tabs: ["https://notes.example"] };
  assert.deepEqual(validate({ ...defaults, views: [admin] }).views[0]?.tabs, ["https://notes.example/"]);
  for (const change of [{ mode: "unknown" }, { tabs: Array(11).fill("https://example.com") }, { tabs: ["file:///etc/passwd"] },
    { url: "https://user:secret@example.com" }, { output: 'DP-1"; exec bad' }]) {
    assert.throws(() => validate({ ...defaults, views: [{ ...admin, ...change }] }));
  }
  assert.throws(() => validate({ ...defaults, views: [admin, admin] }), /distinct/);
});
test("configuration persists atomically and reloads", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "elderbrain-"));
  const file = path.join(dir, "config.json");
  const value = {
    ...defaults,
    configured: true,
    domain: "table.example",
    views: [
      { output: "DP-1", url: "http://one.local" },
      { output: "HDMI-A-1", url: "https://two.local/game" },
    ],
    controllers: { abc: { name: "Seat 1" } },
  };
  saveAtomic(file, value);
  assert.deepEqual(load(file), validate(value));
  assert.equal(fs.statSync(file).mode & 0o777, 0o600);
});
test("invalid URLs and controller IDs are rejected", () => {
  assert.throws(
    () =>
      validate({
        ...defaults,
        views: [{ url: "file:///etc/passwd" }, { url: "http://ok" }],
      }),
    /HTTP/,
  );
  assert.throws(
    () => validate({ ...defaults, controllers: { "bad/id": { name: "x" } } }),
    /controller/,
  );
});
test("Foundry credentials are mode 0600 and never need to be read by UI", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "elderbrain-"));
  const file = path.join(dir, "secrets", "foundry-config.json");
  saveFoundrySecret(file, { username: "u", password: "p" });
  assert.equal(fs.statSync(file).mode & 0o777, 0o600);
  assert.deepEqual(JSON.parse(fs.readFileSync(file, "utf8")), {
    foundry_username: "u",
    foundry_password: "p",
  });
});
