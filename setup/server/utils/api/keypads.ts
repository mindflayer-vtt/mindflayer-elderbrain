import { Readable } from "node:stream";
import type { H3Event } from "h3";
import { command, backupUpload } from "../management";
import { apiBody } from "../api-route";
import type { ControllerMonitor } from "../controllers";
import type { KeypadInventory } from "../keypads";

export async function keypadsApi(event: H3Event, route: string) {
  const method = event.method;
  const socket = process.env.MANAGEMENT_SOCKET || "/run/elderbrain/management.sock";
  const monitor = event.context.monitor as ControllerMonitor;
  const inventory = event.context.inventory as KeypadInventory;
  const body = () => apiBody(event);
  if (route === "keypads/release" && method === "GET") {
    const result = await command(socket, "keypad-release", 180000);
    if (!result.ok) throw new Error("No installable stable release is available, or GitHub could not be reached. A signed serial-install bundle is required; OTA firmware alone is insufficient.");
    return JSON.parse(result.output || "null");
  }
  if ((route === "keypads/install" || route === "keypads/provision") && method === "POST") {
    const input = await body() as Record<string, unknown>;
    if (!input || input.confirm !== true || typeof input.usbId !== "string" || !/^[a-f0-9]{32}$/.test(input.usbId) ||
        typeof input.version !== "string" || !/^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$/.test(input.version) ||
        !Number.isSafeInteger(input.revision) || Number(input.revision) < 1 || typeof input.adopt !== "boolean") throw new Error("Confirm the USB target, expected firmware release and saved settings");
    const payload = Buffer.from(JSON.stringify({ usbId: input.usbId, version: input.version, revision: input.revision, adopt: input.adopt }));
    const provisioning = route === "keypads/provision";
    const result = await backupUpload(socket, Readable.from([payload]), payload.length,
      provisioning ? "keypad-provision-start" : "keypad-install-start");
    if (!result.ok) throw new Error((provisioning ? "Provisioning" : "Installation") + " could not start. Check saved settings, active host jobs and USB connection, then refresh.");
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

  setResponseStatus(event, 404);
  return { error: "not found" };
}
