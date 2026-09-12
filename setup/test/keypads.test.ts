import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { KeypadInventory } from "../server/utils/keypads.ts";
import { bindKeypadInventory } from "../server/utils/keypad-monitor.ts";
import { ControllerMonitor } from "../server/utils/controllers.ts";

test("registered offline devices persist without inventing device confirmation", (t) => {
  const state = fs.mkdtempSync(path.join(os.tmpdir(), "elderbrain-keypads-"));
  t.after(() => fs.rmSync(state, { recursive: true, force: true }));
  const inventory = new KeypadInventory(state);
  inventory.registrations(["offline", "constructor"]);
  assert.equal(inventory.list().length, 2);
  const record = inventory.list().find(r => r.id === "offline")!;
  assert.equal(record.registration, "registered");
  assert.equal(record.connection, "unknown");
  assert.equal(record.appliedRevision, null);
  assert.equal(record.lastSeen, null);
  inventory.rename("offline", { name: "Player one" });
  inventory.registrationsUnavailable();
  assert.equal(inventory.list()[0]!.registration, "unknown");
  inventory.registrations([]);
  assert.equal(inventory.list()[0]!.registration, "absent");
  assert.equal(new KeypadInventory(state).list()[0]!.name, "Player one");
  assert.throws(() => inventory.registrations(["bad/id"]));
  assert.equal(inventory.list().length, 2);
});

test("only authenticated device metadata confirms provisioning and never a configuration revision", (t) => {
  const state = fs.mkdtempSync(path.join(os.tmpdir(), "elderbrain-keypads-"));
  t.after(() => fs.rmSync(state, { recursive: true, force: true }));
  const inventory = new KeypadInventory(state);
  const device = { id: "device", connected: true, lastKey: null, lastActivity: null,
    hardware: "mindflayer-keypad-v1", firmware: "1.2.3" };
  inventory.observe(device);
  assert.equal(inventory.list()[0]!.hardware, null);
  inventory.observe({ ...device, deviceAuthenticated: true, configurationDigest: "a".repeat(64) });
  assert.equal(inventory.list()[0]!.hardware, device.hardware);
  assert.equal(inventory.list()[0]!.firmware, device.firmware);
  assert.equal(inventory.list()[0]!.provisioning, "provisioned");
  assert.equal(inventory.list()[0]!.appliedRevision, null);
  assert.equal(inventory.list()[0]!.configurationDigest, "a".repeat(64));
  inventory.observe({ ...device, firmware: "spoofed", deviceAuthenticated: false });
  assert.equal(inventory.list()[0]!.firmware, device.firmware);
  assert.equal(new KeypadInventory(state).list()[0]!.firmware, device.firmware);
});

test("inventory survives restart and connection loss becomes unknown", (t) => {
  const state = fs.mkdtempSync(path.join(os.tmpdir(), "elderbrain-keypads-"));
  t.after(() => fs.rmSync(state, { recursive: true, force: true }));
  const inventory = new KeypadInventory(state);
  inventory.observe({ id: "keypad-1", connected: true, lastKey: "Q", lastActivity: null });
  inventory.rename("keypad-1", { name: "Alice", seat: "North" });
  assert.equal(inventory.list()[0]!.connection, "connected");
  inventory.disconnected();
  assert.equal(inventory.list()[0]!.connection, "unknown");
  const restored = new KeypadInventory(state);
  assert.equal(restored.list()[0]!.name, "Alice");
  assert.equal(restored.list()[0]!.connection, "unknown");
  assert.equal(restored.list()[0]!.provisioning, "observed");
});
test("Wi-Fi settings are private and desired changes do not claim device application", (t) => {
  const state = fs.mkdtempSync(path.join(os.tmpdir(), "elderbrain-keypads-"));
  t.after(() => fs.rmSync(state, { recursive: true, force: true }));
  const inventory = new KeypadInventory(state);
  inventory.observe({ id: "keypad-1", connected: false, lastKey: null, lastActivity: null });
  inventory.configure({ ssid: "Table", psk: "private-wifi-password", serverHost: "192.168.1.2" });
  assert.equal(inventory.list()[0]!.desiredRevision, 1);
  assert.equal(inventory.list()[0]!.appliedRevision, null);
  assert.equal(inventory.publicSettings().passwordStored, true);
  assert.equal(JSON.stringify(inventory.publicSettings()).includes("private-wifi-password"), false);
  assert.equal(fs.statSync(path.join(state, "secrets/keypad-settings.json")).mode & 0o777, 0o600);
  inventory.configure({ ssid: "New Table", serverHost: "192.168.1.3" });
  assert.equal(new KeypadInventory(state).publicSettings().passwordStored, true);
  assert.throws(() => inventory.configure({ ssid: "x", psk: "short", serverHost: "x" }), /PSK/);
  for (const psk of ["a".repeat(64), "é".repeat(32), "password\0", {}, 12345678]) {
    assert.throws(() => inventory.configure({ ssid: "x", psk, serverHost: "x" }), /PSK/);
  }
  assert.throws(() => inventory.configure({ ssid: "x\0", psk: "password", serverHost: "x" }), /SSID/);
  assert.equal(inventory.publicSettings().revision, 2);
});

test("LED overrides persist, validate before mutation and never claim device confirmation", (t) => {
  const state = fs.mkdtempSync(path.join(os.tmpdir(), "elderbrain-keypads-"));
  t.after(() => fs.rmSync(state, { recursive: true, force: true }));
  const inventory = new KeypadInventory(state);
  inventory.registrations(["offline"]);
  const input = { name: "Alice", seat: "North", ledPreferences: { led1: "#FF8000", led2: "#0080ff" } };
  const record = inventory.rename("offline", input);
  assert.deepEqual(record.ledPreferences, { led1: "#ff8000", led2: "#0080ff" });
  assert.equal(record.desiredRevision, 1);
  assert.equal(record.appliedRevision, null);
  assert.equal(new KeypadInventory(state).list()[0]!.ledPreferences?.led1, "#ff8000");
  assert.throws(() => inventory.rename("offline", { ...input, name: "changed", ledPreferences: { led1: "red", led2: "#ffffff" } }), /LED/);
  assert.equal(inventory.list()[0]!.name, "Alice");
  inventory.rename("offline", input);
  assert.equal(inventory.list()[0]!.desiredRevision, 1);
  inventory.configure({ ssid: "Table", psk: "private-wifi-password", serverHost: "192.168.1.2" });
  assert.equal(inventory.list()[0]!.desiredRevision, 2);
  inventory.rename("offline", { ...input, ledPreferences: null });
  assert.equal(inventory.list()[0]!.ledPreferences, null);
  assert.equal(inventory.list()[0]!.desiredRevision, 3);
  assert.equal(inventory.list()[0]!.appliedRevision, null);
});

test("saved LEDs are sent once per connection, not per key press, and remain unconfirmed", (t) => {
  const state = fs.mkdtempSync(path.join(os.tmpdir(), "elderbrain-keypads-"));
  t.after(() => fs.rmSync(state, { recursive: true, force: true }));
  const inventory = new KeypadInventory(state);
  inventory.registrations(["keypad"]);
  inventory.rename("keypad", { ledPreferences: { led1: "#ff0000", led2: "#0000ff" } });
  const monitor = new ControllerMonitor("ws://unused");
  const sends: string[] = [];
  monitor.configureLeds = id => { sends.push(id); };
  bindKeypadInventory(monitor, inventory);
  const controller = { id: "keypad", connected: true, lastKey: null, lastActivity: null };
  monitor.emit("change", controller);
  monitor.emit("change", { ...controller, lastKey: "Q" });
  assert.deepEqual(sends, ["keypad"]);
  monitor.emit("unavailable");
  assert.equal(inventory.list()[0]!.connection, "unknown");
  monitor.emit("change", controller);
  assert.deepEqual(sends, ["keypad", "keypad"]);
  assert.equal(inventory.list()[0]!.appliedRevision, null);
  inventory.rename("keypad", { ledPreferences: null });
  monitor.emit("unavailable");
  monitor.emit("change", controller);
  assert.equal(sends.length, 2);
});

test("only a matching authenticated online proof confirms the expected saved revision", (t) => {
  const state = fs.mkdtempSync(path.join(os.tmpdir(), "elderbrain-keypads-"));
  t.after(() => fs.rmSync(state, { recursive: true, force: true }));
  let inventory = new KeypadInventory(state);
  inventory.registrations(["device"]);
  const settings = { ssid: "Table", psk: "private-wifi-password", serverHost: "192.168.1.2" };
  inventory.configure(settings);
  const device = { id: "device", connected: true, lastKey: null, lastActivity: null,
    deviceAuthenticated: true, configurationDigest: "a".repeat(64) };
  inventory.expectProvisioning("device", 1, device.configurationDigest);
  assert.equal(inventory.list()[0]!.appliedRevision, null);
  assert.equal(fs.statSync(path.join(state, "secrets/keypad-expectations.json")).mode & 0o777, 0o600);
  inventory = new KeypadInventory(state);
  for (const report of [
    { ...device, deviceAuthenticated: false },
    { ...device, connected: false },
    { ...device, configurationDigest: "b".repeat(64) },
    { ...device, configurationDigest: "malformed" },
  ]) {
    inventory.observe(report);
    assert.equal(inventory.list()[0]!.appliedRevision, null);
  }
  inventory.observe(device);
  assert.equal(inventory.list()[0]!.appliedRevision, 1);
  inventory.configure({ ...settings, ssid: "Changed" });
  inventory.observe(device);
  assert.equal(inventory.list()[0]!.desiredRevision, 2);
  assert.equal(inventory.list()[0]!.appliedRevision, 1);
  assert.throws(() => inventory.expectProvisioning("device", 1, device.configurationDigest), /Stale/);
  assert.throws(() => inventory.expectProvisioning("missing", 2, device.configurationDigest), /unknown/);
  assert.throws(() => inventory.expectProvisioning("device", 2, "bad"), /digest/);
  inventory.expectProvisioning("device", 2, "b".repeat(64));
  inventory.observe(device);
  assert.equal(inventory.list()[0]!.appliedRevision, 1);
  inventory.observe({ ...device, configurationDigest: "b".repeat(64) });
  assert.equal(new KeypadInventory(state).list()[0]!.appliedRevision, 2);
});

test("provisioning proof cannot acknowledge LEDs or a superseded installation revision", (t) => {
  const state = fs.mkdtempSync(path.join(os.tmpdir(), "elderbrain-keypads-"));
  t.after(() => fs.rmSync(state, { recursive: true, force: true }));
  const inventory = new KeypadInventory(state);
  inventory.registrations(["device"]);
  inventory.configure({ ssid: "Table", psk: "private-wifi-password", serverHost: "192.168.1.2" });
  const device = { id: "device", connected: true, lastKey: null, lastActivity: null,
    deviceAuthenticated: true, configurationDigest: "a".repeat(64) };
  inventory.expectProvisioning("device", 1, device.configurationDigest);
  inventory.rename("device", { ledPreferences: { led1: "#ff0000", led2: "#0000ff" } });
  inventory.observe(device);
  assert.equal(inventory.list()[0]!.appliedRevision, null);
  inventory.expectProvisioning("device", 2, device.configurationDigest);
  inventory.observe(device);
  assert.equal(inventory.list()[0]!.appliedRevision, null);
  inventory.rename("device", { ledPreferences: null });
  inventory.observe(device);
  assert.equal(inventory.list()[0]!.appliedRevision, null);
});

test("completed installation receipts confirm only matching settings and preserve live connection state", t => {
  const state = fs.mkdtempSync(path.join(os.tmpdir(), "elderbrain-keypads-"));
  t.after(() => fs.rmSync(state, { recursive: true, force: true }));
  const inventory = new KeypadInventory(state);
  inventory.registrations(["device"]);
  const settings = { ssid: "Table", psk: "private-wifi-password", serverHost: "table.local" };
  inventory.configure(settings);
  const receipt = { deviceId: "device", revision: 1, configurationVerifiedAt: 1000, configurationDigest: "a".repeat(64), matchesCurrentSettings: true, currentSettingsRevision: 1 };
  inventory.installationReceipts([receipt]);
  assert.equal(inventory.list()[0]!.appliedRevision, 1);
  assert.equal(inventory.list()[0]!.appliedProvisioningRevision, 1);
  assert.equal(inventory.list()[0]!.connection, "unknown");
  inventory.configure({ ...settings, ssid: "Changed" });
  inventory.installationReceipts([receipt]);
  assert.equal(inventory.list()[0]!.appliedRevision, 1);
  inventory.rename("device", { ledPreferences: { led1: "#ffffff", led2: "#ffffff" } });
  inventory.installationReceipts([{ ...receipt, revision: 2, currentSettingsRevision: 2, configurationVerifiedAt: 2000 }]);
  assert.equal(inventory.list()[0]!.appliedProvisioningRevision, 2);
  assert.equal(inventory.list()[0]!.appliedRevision, 1);
  assert.equal(new KeypadInventory(state).list()[0]!.appliedProvisioningRevision, 2);
  assert.throws(() => inventory.installationReceipts([{ ...receipt, configurationDigest: "invalid" }]));
});

test("full LED revision requires current provisioning and current authenticated colours", t => {
  const state = fs.mkdtempSync(path.join(os.tmpdir(), "elderbrain-keypads-"));
  t.after(() => fs.rmSync(state, { recursive: true, force: true }));
  const inventory = new KeypadInventory(state);
  inventory.registrations(["device"]);
  const settings = { ssid: "Table", psk: "private-wifi-password", serverHost: "table.local" };
  inventory.configure(settings);
  const leds = { led1: "#ff0000", led2: "#0000ff" };
  inventory.rename("device", { ledPreferences: leds });
  const device = { id: "device", connected: true, lastKey: null, lastActivity: null,
    deviceAuthenticated: true, configurationDigest: "a".repeat(64), appliedLeds: leds };
  const record = () => inventory.list()[0]!;
  inventory.observe(device);
  assert.equal(record().appliedRevision, null);
  inventory.installationReceipts([{ deviceId: "device", revision: 1, configurationVerifiedAt: 1000,
    configurationDigest: device.configurationDigest, matchesCurrentSettings: true, currentSettingsRevision: 1 }]);
  assert.equal(record().appliedRevision, 2);
  assert.equal(record().appliedProvisioningRevision, 1);
  for (const change of [
    { appliedLeds: null }, { appliedLeds: { ...leds, led1: "#ffffff" } },
    { deviceAuthenticated: false }, { connected: false }, { configurationDigest: "b".repeat(64) },
  ]) {
    inventory.observe({ ...device, ...change });
    assert.equal(record().appliedRevision, null);
    inventory.observe(device);
    assert.equal(record().appliedRevision, 2);
  }
  inventory.rename("device", { ledPreferences: { ...leds, led1: "#ffffff" } });
  inventory.observe(device);
  assert.equal(record().desiredRevision, 3);
  assert.equal(record().appliedRevision, 2);
  const updated = { ...device, appliedLeds: { ...leds, led1: "#ffffff" } };
  inventory.observe(updated);
  assert.equal(record().appliedRevision, 3);
  inventory.configure({ ...settings, ssid: "Changed" });
  inventory.observe(updated);
  assert.equal(record().desiredRevision, 4);
  assert.equal(record().appliedRevision, 3);
  inventory.disconnected();
  assert.equal(record().appliedLeds, null);
  const restored = new KeypadInventory(state);
  restored.observe(updated);
  assert.equal(restored.list()[0]!.appliedRevision, 3);
});
