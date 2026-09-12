import fs from "node:fs";
import path from "node:path";
import type { Controller } from "../../shared/types";

export interface KeypadRecord {
  id: string; name: string; seat: string; hardware: string | null;
  firmware: string | null; connection: "connected" | "disconnected" | "unknown";
  lastSeen: string | null; provisioning: "observed" | "provisioned" | "failed" | "pending";
  desiredRevision: number; appliedRevision: number | null;
  registration?: "registered" | "absent" | "unknown";
  ledPreferences?: { led1: string; led2: string } | null;
  appliedLeds?: { led1: string; led2: string } | null;
  configurationDigest?: string | null;
  appliedProvisioningRevision?: number | null;
  installationVerifiedAt?: number;
  chipMac?: string;
}
interface Settings { revision: number; ssid: string; psk: string; serverHost: string; serverPort: number }
interface ProvisioningExpectation { revision: number; digest: string; settingsRevision?: number }
function atomic(file: string, value: unknown) {
  fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  fs.writeFileSync(file + ".tmp", JSON.stringify(value), { mode: 0o600 });
  fs.renameSync(file + ".tmp", file);
}
function read<T>(file: string, fallback: T): T {
  try { return JSON.parse(fs.readFileSync(file, "utf8")); }
  catch (e) { if ((e as NodeJS.ErrnoException).code === "ENOENT") return fallback; throw e; }
}
export class KeypadInventory {
  private records: Record<string, KeypadRecord>;
  private settings: Settings;
  private expectations: Record<string, ProvisioningExpectation>;
  constructor(private state: string) {
    this.records = Object.assign(Object.create(null), read(path.join(state, "keypads.json"), {}));
    this.settings = read(path.join(state, "secrets/keypad-settings.json"), { revision: 0, ssid: "", psk: "", serverHost: "", serverPort: 10443 });
    this.expectations = Object.assign(Object.create(null), read(path.join(state, "secrets/keypad-expectations.json"), {}));
    this.disconnected();
  }
  private save() { atomic(path.join(this.state, "keypads.json"), this.records); }
  private reconcileLeds(record: KeypadRecord) {
    if (!record.ledPreferences) return;
    const expected = this.expectations[record.id];
    const matches = record.appliedLeds?.led1 === record.ledPreferences.led1 &&
      record.appliedLeds?.led2 === record.ledPreferences.led2;
    if (record.connection === "connected" && matches && expected &&
        expected.settingsRevision === this.settings.revision &&
        expected.digest === record.configurationDigest) record.appliedRevision = record.desiredRevision;
    else if (record.appliedRevision === record.desiredRevision) record.appliedRevision = null;
  }
  observe(controller: Controller) {
    if (!/^[A-Za-z0-9._-]{1,64}$/.test(controller.id)) return;
    const record = this.records[controller.id] || {
      id: controller.id, name: "", seat: "", hardware: null, firmware: null,
      connection: "unknown", lastSeen: null, provisioning: "observed",
      desiredRevision: this.settings.revision, appliedRevision: null,
    };
    record.connection = controller.connected ? "connected" : "disconnected";
    record.appliedLeds = null;
    if (controller.connected && controller.deviceAuthenticated === true) {
      if (controller.appliedLeds && /^#[a-f0-9]{6}$/.test(controller.appliedLeds.led1) &&
          /^#[a-f0-9]{6}$/.test(controller.appliedLeds.led2)) record.appliedLeds = { ...controller.appliedLeds };
      record.configurationDigest = /^[a-f0-9]{64}$/.test(controller.configurationDigest || "") ? controller.configurationDigest! : null;
      const expected = this.expectations[record.id];
      // A provisioning proof does not acknowledge transient LED commands. Only
      // confirm the current revision when its complete device state is covered.
      if (expected && expected.revision === record.desiredRevision &&
          expected.digest === record.configurationDigest && !record.ledPreferences) {
        record.appliedRevision = expected.revision;
      }
      if (controller.hardware) record.hardware = controller.hardware;
      if (controller.firmware) record.firmware = controller.firmware;
      if (controller.hardware && controller.firmware) record.provisioning = "provisioned";
    }
    else record.configurationDigest = null;
    this.reconcileLeds(record);
    if (controller.connected) record.lastSeen = new Date().toISOString();
    this.records[record.id] = record;
    this.save();
  }
  disconnected() {
    for (const record of Object.values(this.records)) {
      record.connection = "unknown";
      record.appliedLeds = null;
      record.configurationDigest = null;
      this.reconcileLeds(record);
    }
    this.save();
  }
  list() { return Object.values(this.records).map(record => ({ ...record })); }
  installationReceipts(input: unknown) {
    if (!Array.isArray(input)) throw new Error("Invalid installation receipts");
    for (const receipt of input) {
      if (!receipt || typeof receipt !== "object" || typeof receipt.deviceId !== "string" ||
          !/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(receipt.deviceId) ||
          !Number.isSafeInteger(receipt.revision) || receipt.revision < 1 ||
          !Number.isSafeInteger(receipt.configurationVerifiedAt) || receipt.configurationVerifiedAt < 1 ||
          typeof receipt.configurationDigest !== "string" || !/^[a-f0-9]{64}$/.test(receipt.configurationDigest)) throw new Error("Invalid installation receipt");
    }
    for (const receipt of input) {
      const record = this.records[receipt.deviceId];
      if (!record || record.registration !== "registered" || receipt.configurationVerifiedAt <= (record.installationVerifiedAt || 0)) continue;
      record.installationVerifiedAt = receipt.configurationVerifiedAt;
      if (typeof receipt.chipMac === "string" && /^[a-f0-9]{2}(?::[a-f0-9]{2}){5}$/.test(receipt.chipMac)) record.chipMac = receipt.chipMac;
      record.appliedProvisioningRevision = receipt.revision;
      record.provisioning = "provisioned";
      if (!record.lastSeen || Date.parse(record.lastSeen) <= receipt.configurationVerifiedAt) {
        if (receipt.hardware === "mindflayer-keypad-v1") record.hardware = receipt.hardware;
        if (typeof receipt.firmware === "string" && /^[A-Za-z0-9.+_-]{1,47}$/.test(receipt.firmware)) record.firmware = receipt.firmware;
      }
      if (receipt.matchesCurrentSettings === true && receipt.currentSettingsRevision === this.settings.revision &&
          receipt.revision === record.desiredRevision && !record.ledPreferences) record.appliedRevision = receipt.revision;
      if (receipt.matchesCurrentSettings === true && receipt.currentSettingsRevision === this.settings.revision) {
        this.expectations[record.id] = { revision: receipt.revision, digest: receipt.configurationDigest, settingsRevision: this.settings.revision };
        this.reconcileLeds(record);
      }
    }
    atomic(path.join(this.state, "secrets/keypad-expectations.json"), this.expectations);
    this.save();
  }
  registrations(identities: unknown) {
    if (!Array.isArray(identities) || identities.some(id => typeof id !== "string" || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(id))) throw new Error("Invalid registration inventory");
    const registered = new Set<string>(identities);
    for (const id of registered) {
      this.records[id] ||= { id, name: "", seat: "", hardware: null, firmware: null,
        connection: "unknown", lastSeen: null, provisioning: "pending",
        desiredRevision: this.settings.revision, appliedRevision: null };
    }
    for (const record of Object.values(this.records)) record.registration = registered.has(record.id) ? "registered" : "absent";
    this.save();
  }
  registrationsUnavailable() {
    for (const record of Object.values(this.records)) record.registration = "unknown";
    this.save();
  }
  publicSettings() {
    const { psk, ...settings } = this.settings;
    return { ...settings, passwordStored: !!psk };
  }
  // Internal installation-job boundary, never accept a browser-supplied digest.
  // The job must hash the exact canonical envelope it will send to the keypad.
  expectProvisioning(id: string, revision: number, digest: string) {
    const record = this.records[id];
    if (!record || !Number.isSafeInteger(revision) || revision < 1 || revision !== record.desiredRevision) throw new Error("Stale or unknown keypad configuration");
    if (!/^[a-f0-9]{64}$/.test(digest)) throw new Error("Invalid provisioning digest");
    const next = Object.assign(Object.create(null), this.expectations, { [id]: { revision, digest, settingsRevision: this.settings.revision } });
    atomic(path.join(this.state, "secrets/keypad-expectations.json"), next);
    this.expectations = next;
  }
  configure(input: Record<string, unknown>) {
    const ssid = typeof input.ssid === "string" ? input.ssid : "";
    const psk = input.psk === undefined ? this.settings.psk : input.psk;
    const serverHost = typeof input.serverHost === "string" ? input.serverHost.trim() : "";
    const serverPort = Number(input.serverPort ?? 10443);
    if (!ssid || ssid.includes("\0") || Buffer.byteLength(ssid) > 32) throw new Error("Wi-Fi SSID must contain 1–32 bytes without NUL characters");
    // Match the firmware provisioning schema's 63-byte password field. A raw
    // 64-digit PSK cannot currently be represented by that schema.
    if (typeof psk !== "string" || psk.includes("\0") || Buffer.byteLength(psk) < 8 || Buffer.byteLength(psk) > 63) throw new Error("Wi-Fi PSK must contain 8–63 bytes without NUL characters; raw 64-digit PSKs are not supported by the firmware");
    if (!/^[a-zA-Z0-9.:-]{1,253}$/.test(serverHost) || !Number.isInteger(serverPort) || serverPort < 1 || serverPort > 65535) throw new Error("Invalid appliance address or port");
    const revision = Math.max(this.settings.revision, ...Object.values(this.records).map(record => record.desiredRevision)) + 1;
    const next = { revision, ssid, psk, serverHost, serverPort };
    atomic(path.join(this.state, "secrets/keypad-settings.json"), next);
    this.settings = next;
    for (const record of Object.values(this.records)) record.desiredRevision = revision;
    this.save();
    return this.publicSettings();
  }
  rename(id: string, input: Record<string, unknown>) {
    const record = this.records[id];
    if (!record) throw new Error("Unknown keypad");
    let leds = record.ledPreferences;
    if (input.ledPreferences !== undefined) {
      const value = input.ledPreferences;
      if (value === null) leds = null;
      else {
        if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Invalid LED preferences");
        const { led1, led2 } = value as Record<string, unknown>;
        if (typeof led1 !== "string" || typeof led2 !== "string" || !/^#[0-9a-f]{6}$/i.test(led1) || !/^#[0-9a-f]{6}$/i.test(led2)) throw new Error("LED colours must be six-digit hexadecimal values");
        leds = { led1: led1.toLowerCase(), led2: led2.toLowerCase() };
      }
    }
    if (JSON.stringify(leds) !== JSON.stringify(record.ledPreferences)) record.desiredRevision += 1;
    record.ledPreferences = leds;
    record.name = String(input.name || "").slice(0, 80);
    record.seat = String(input.seat || "").slice(0, 80);
    this.save();
    return { ...record };
  }
}
