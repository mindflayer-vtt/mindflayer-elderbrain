import { Readable } from "node:stream";
import { command, backupUpload } from "./management-client";
import type { ControllerMonitor } from "./controller-monitor";
import type { KeypadInventory } from "./keypad-inventory";

const socket = () => process.env.MANAGEMENT_SOCKET || "/run/elderbrain/management.sock";

export async function installableRelease() {
  const result = await command(socket(), "keypad-release", 180000);
  if (!result.ok) throw new Error("No installable stable release is available, or GitHub could not be reached. A signed serial-install bundle is required; OTA firmware alone is insufficient.");
  return JSON.parse(result.output || "null");
}

async function startKeypadJob(input: Record<string, unknown>, action: "install" | "provision") {
  if (!input || input.confirm !== true || typeof input.usbId !== "string" || !/^[a-f0-9]{32}$/.test(input.usbId) ||
      typeof input.version !== "string" || !/^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$/.test(input.version) ||
      !Number.isSafeInteger(input.revision) || Number(input.revision) < 1 || typeof input.adopt !== "boolean")
    throw new Error("Confirm the USB target, expected firmware release and saved settings");
  const payload = Buffer.from(JSON.stringify({ usbId: input.usbId, version: input.version, revision: input.revision, adopt: input.adopt }));
  const result = await backupUpload(socket(), Readable.from([payload]), payload.length, `keypad-${action}-start`);
  if (!result.ok) throw new Error((action === "provision" ? "Provisioning" : "Installation") + " could not start. Check saved settings, active host jobs and USB connection, then refresh.");
  return JSON.parse(result.output || "null");
}

export const installKeypad = (input: Record<string, unknown>) => startKeypadJob(input, "install");
export const provisionKeypad = (input: Record<string, unknown>) => startKeypadJob(input, "provision");

export async function usbDevices() {
  const result = await command(socket(), "keypad-usb-devices");
  if (!result.ok) throw new Error("USB discovery unavailable");
  return JSON.parse(result.output || "null");
}

export async function registeredKeypads(inventory: KeypadInventory) {
  let inventorySource: "current" | "unavailable" = "current";
  let installationSource: "current" | "unavailable" = "current";
  try {
    const result = await command(socket(), "keypad-registrations");
    if (!result.ok) throw new Error("Registrations unavailable");
    inventory.registrations(JSON.parse(result.output || "null"));
  } catch {
    inventory.registrationsUnavailable();
    inventorySource = "unavailable";
  }
  try {
    const receipts = await command(socket(), "keypad-installations");
    if (!receipts.ok) throw new Error("Installation receipts unavailable");
    inventory.installationReceipts(JSON.parse(receipts.output || "null"));
  } catch { installationSource = "unavailable"; }
  return { keypads: inventory.list(), inventorySource, installationSource };
}

export const keypadSettings = (inventory: KeypadInventory) => inventory.publicSettings();
export const configureKeypads = (inventory: KeypadInventory, input: Record<string, unknown>) => inventory.configure(input);

export function renameKeypad(inventory: KeypadInventory, monitor: ControllerMonitor, id: string, input: Record<string, unknown>) {
  if (!/^[A-Za-z0-9._-]{1,64}$/.test(id)) return null;
  const record = inventory.rename(id, input);
  let ledDelivery: "sent" | "pending" | "disabled" = record.ledPreferences ? "pending" : "disabled";
  if (input.ledPreferences !== undefined && record.ledPreferences) {
    try { monitor.configureLeds(record.id, record.ledPreferences); ledDelivery = "sent"; } catch {}
  }
  return { ...record, ledDelivery };
}
