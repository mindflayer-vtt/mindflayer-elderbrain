import type { ControllerMonitor } from "./controllers";
import type { KeypadInventory } from "./keypads";

export function bindKeypadInventory(monitor: ControllerMonitor, inventory: KeypadInventory) {
  monitor.on("change", controller => {
    const saved = inventory.list().find(record => record.id === controller.id);
    inventory.observe(controller);
    if (controller.connected && saved?.connection !== "connected" && saved?.ledPreferences) {
      // Sending is not acknowledgement. Keep appliedRevision unchanged.
      try { monitor.configureLeds(controller.id, saved.ledPreferences); } catch {}
    }
  });
  monitor.on("unavailable", () => inventory.disconnected());
}
