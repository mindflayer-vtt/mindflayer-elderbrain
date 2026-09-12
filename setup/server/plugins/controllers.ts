import { ControllerMonitor } from "../utils/controllers";
import { KeypadInventory } from "../utils/keypads";
import { bindKeypadInventory } from "../utils/keypad-monitor";

export default defineNitroPlugin((app) => {
  const inventory = new KeypadInventory(process.env.STATE_DIR || "/state");
  const monitor = new ControllerMonitor(process.env.MINDFLAYER_WS_URL || "ws://mindflayer-server:8080/ws").start();
  bindKeypadInventory(monitor, inventory);
  app.hooks.hook("request", (event) => { event.context.monitor = monitor; event.context.inventory = inventory; });
  app.hooks.hook("close", () => { monitor.stop(); });
});
