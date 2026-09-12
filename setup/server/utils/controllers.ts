import WebSocket from "ws";
import { EventEmitter } from "node:events";
import type { Controller } from "../../shared/types";

function appliedLeds(value: unknown): Controller["appliedLeds"] {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const leds = value as Record<string, unknown>;
  function colour(input: unknown): string | null {
    if (!input || typeof input !== "object" || Array.isArray(input)) return null;
    const rgb = input as Record<string, unknown>;
    const channels = [rgb.r, rgb.g, rgb.b];
    if (!channels.every(channel => typeof channel === "number" && Number.isInteger(channel) && channel >= 0 && channel <= 255)) return null;
    return "#" + channels.map(channel => (channel as number).toString(16).padStart(2, "0")).join("");
  }
  const led1 = colour(leds.led1), led2 = colour(leds.led2);
  return led1 && led2 ? { led1, led2 } : null;
}

export class ControllerMonitor extends EventEmitter {
  url: string;
  WebSocketClass: typeof WebSocket;
  controllers = new Map<string, Controller>();
  socket: WebSocket | null = null;
  timer: ReturnType<typeof setTimeout> | null = null;
  stopped = false;
  constructor(url: string, WebSocketClass = WebSocket) {
    super();
    this.url = url;
    this.WebSocketClass = WebSocketClass;
    this.controllers = new Map();
    this.socket = null;
    this.timer = null;
  }
  start() {
    this.stopped = false;
    this.#connect();
    return this;
  }
  stop() {
    this.stopped = true;
    if (this.timer) clearTimeout(this.timer);
    this.socket?.close();
    this.emit("unavailable");
  }
  #connect() {
    const ws = (this.socket = new this.WebSocketClass(this.url));
    ws.on("open", () =>
      ws.send(
        JSON.stringify({ type: "registration", receiver: true, players: [] }),
      ),
    );
    ws.on("message", (data) => {
      let message: Record<string, unknown>;
      try {
        const parsed: unknown = JSON.parse(data.toString());
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return;
        message = parsed as Record<string, unknown>;
      } catch {
        return;
      }
      const id = message["controller-id"];
      if (typeof id !== "string" || !id) return;
      const current: Controller = this.controllers.get(id) || {
        id,
        connected: false,
        lastKey: null,
        lastActivity: null,
      };
      if (message.type === "registration") {
        current.connected = message.status !== "disconnected";
        current.deviceAuthenticated = message.deviceAuthenticated === true;
        current.appliedLeds = current.connected && current.deviceAuthenticated ? appliedLeds(message.appliedLeds) : null;
        current.hardware = current.deviceAuthenticated && typeof message.hardware === "string" && /^[A-Za-z0-9._-]{1,64}$/.test(message.hardware) ? message.hardware : null;
        current.firmware = current.deviceAuthenticated && typeof message.firmware === "string" && /^[A-Za-z0-9.+_-]{1,47}$/.test(message.firmware) ? message.firmware : null;
        current.configurationDigest = current.deviceAuthenticated && typeof message.configurationDigest === "string" && /^[0-9a-f]{64}$/.test(message.configurationDigest) ? message.configurationDigest : null;
      }
      if (message.type === "configuration-state") {
        if (!current.connected || current.deviceAuthenticated !== true || message.deviceAuthenticated !== true ||
            typeof message.configurationDigest !== "string" || !/^[0-9a-f]{64}$/.test(message.configurationDigest)) return;
        current.configurationDigest = message.configurationDigest;
      }
      if (message.type === "led-state") {
        if (!current.connected || current.deviceAuthenticated !== true || message.deviceAuthenticated !== true) return;
        current.appliedLeds = appliedLeds(message.appliedLeds);
      }
      if (message.type === "key-event") {
        current.lastKey = typeof message.key === "string" ? message.key : null;
        current.lastState = typeof message.state === "boolean" ? message.state : undefined;
        current.lastActivity = new Date().toISOString();
      }
      this.controllers.set(id, current);
      this.emit("change", current);
    });
    ws.on("close", () => {
      for (const controller of this.controllers.values()) {
        controller.connected = false;
        controller.appliedLeds = null;
      }
      this.emit("unavailable");
      if (!this.stopped && this.socket === ws)
        this.timer = setTimeout(() => this.#connect(), 2000);
    });
    ws.on("error", () => {});
  }
  identify(id: string) {
    this.configureLeds(id, { led1: "#ff00ff", led2: "#ffffff" });
  }
  configureLeds(id: string, preferences: { led1: string; led2: string }) {
    if (
      !this.controllers.get(id)?.connected ||
      this.socket?.readyState !== this.WebSocketClass.OPEN
    )
      throw new Error("controller is not connected");
    function colour(value: string) {
      if (!/^#[0-9a-f]{6}$/i.test(value)) throw new Error("Invalid LED colour");
      return { r: parseInt(value.slice(1, 3), 16), g: parseInt(value.slice(3, 5), 16), b: parseInt(value.slice(5, 7), 16) };
    }
    this.socket.send(
      JSON.stringify({
        type: "configuration",
        "controller-id": id,
        led1: colour(preferences.led1),
        led2: colour(preferences.led2),
      }),
    );
  }
  snapshot() {
    return [...this.controllers.values()];
  }
}
