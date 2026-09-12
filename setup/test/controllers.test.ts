import test from "node:test";
import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { ControllerMonitor } from "../server/utils/controllers.ts";
import type WebSocket from "ws";

class FakeSocket extends EventEmitter {
  readyState: number;
  sent: any[];
  static OPEN = 1;
  constructor() {
    super();
    this.readyState = 1;
    this.sent = [];
    queueMicrotask(() => this.emit("open"));
  }
  send(value: string) {
    this.sent.push(JSON.parse(value));
  }
  close() {}
}
test("uses receiver protocol for discovery, activity and identification", async (t) => {
  const monitor = new ControllerMonitor("ws://example", FakeSocket as unknown as typeof WebSocket).start();
  t.after(() => monitor.stop());
  await new Promise((r) => setImmediate(r));
  const peer = monitor.socket as unknown as FakeSocket;
  peer.emit(
    "message",
    JSON.stringify({
      type: "registration",
      "controller-id": "09af3c",
      status: "connected",
      receiver: false,
    }),
  );
  peer.emit(
    "message",
    JSON.stringify({
      type: "key-event",
      "controller-id": "09af3c",
      key: "Q",
      state: true,
    }),
  );
  assert.equal(monitor.snapshot()[0]!.lastKey, "Q");
  monitor.identify("09af3c");
  assert.equal(peer.sent[0].receiver, true);
  assert.equal(peer.sent[1].type, "configuration");
  assert.equal(peer.sent[1]["controller-id"], "09af3c");
  monitor.configureLeds("09af3c", { led1: "#ff8000", led2: "#0080ff" });
  assert.deepEqual(peer.sent[2].led1, { r: 255, g: 128, b: 0 });
  assert.deepEqual(peer.sent[2].led2, { r: 0, g: 128, b: 255 });
  assert.throws(() => monitor.configureLeds("09af3c", { led1: "red", led2: "#ffffff" }));
  peer.emit("message", JSON.stringify({ type: "registration", "controller-id": "09af3c", status: "disconnected" }));
  assert.throws(() => monitor.identify("09af3c"), /not connected/);
  assert.throws(() => monitor.configureLeds("09af3c", { led1: "#ff8000", led2: "#0080ff" }), /not connected/);
  assert.equal(peer.sent.length, 3);
  peer.emit("message", JSON.stringify({ type: "registration", "controller-id": "09af3c", status: "connected",
    deviceAuthenticated: true, hardware: "mindflayer-keypad-v1", firmware: "1.2.3" }));
  assert.equal(monitor.snapshot()[0]!.firmware, "1.2.3");
  peer.emit("message", JSON.stringify({ type: "configuration-state", "controller-id": "09af3c",
    deviceAuthenticated: true, configurationDigest: "a".repeat(64) }));
  assert.equal(monitor.snapshot()[0]!.configurationDigest, "a".repeat(64));
  peer.emit("message", JSON.stringify({ type: "configuration-state", "controller-id": "09af3c",
    deviceAuthenticated: false, configurationDigest: "b".repeat(64) }));
  assert.equal(monitor.snapshot()[0]!.configurationDigest, "a".repeat(64));
  peer.emit("message", JSON.stringify({ type: "registration", "controller-id": "09af3c", status: "connected",
    deviceAuthenticated: false, hardware: "forged", firmware: "9.9.9" }));
  assert.equal(monitor.snapshot()[0]!.firmware, null);
  assert.equal(monitor.snapshot()[0]!.configurationDigest, null);
});

test("LED confirmation requires an authenticated connected device and clears on pending or disconnect", async t => {
  const monitor = new ControllerMonitor("ws://example", FakeSocket as unknown as typeof WebSocket).start();
  t.after(() => monitor.stop());
  await new Promise(r => setImmediate(r));
  const peer = monitor.socket as unknown as FakeSocket;
  const colours = { led1: { r: 0, g: 128, b: 255 }, led2: { r: 255, g: 0, b: 1 } };
  const send = (message: object) => peer.emit("message", JSON.stringify({ "controller-id": "keypad", ...message }));
  const state = () => monitor.snapshot()[0]!.appliedLeds;
  send({ type: "registration", status: "connected", deviceAuthenticated: false, appliedLeds: colours });
  send({ type: "led-state", deviceAuthenticated: true, appliedLeds: colours });
  assert.equal(state(), null);
  send({ type: "registration", status: "connected", deviceAuthenticated: true, appliedLeds: colours });
  assert.deepEqual(state(), { led1: "#0080ff", led2: "#ff0001" });
  send({ type: "led-state", deviceAuthenticated: false, appliedLeds: null });
  assert.deepEqual(state(), { led1: "#0080ff", led2: "#ff0001" });
  send({ type: "led-state", deviceAuthenticated: true, appliedLeds: null });
  assert.equal(state(), null);
  for (const invalid of [null, [], {}, { ...colours, led1: { r: 256, g: 0, b: 0 } }, { ...colours, led2: { r: "1", g: 0, b: 0 } }]) {
    send({ type: "led-state", deviceAuthenticated: true, appliedLeds: invalid });
    assert.equal(state(), null);
  }
  send({ type: "led-state", deviceAuthenticated: true, appliedLeds: colours });
  assert.deepEqual(state(), { led1: "#0080ff", led2: "#ff0001" });
  send({ type: "registration", status: "disconnected", deviceAuthenticated: true, appliedLeds: colours });
  send({ type: "led-state", deviceAuthenticated: true, appliedLeds: colours });
  assert.equal(state(), null);
  send({ type: "registration", status: "connected", deviceAuthenticated: true, appliedLeds: colours });
  monitor.stopped = true;
  peer.emit("close");
  assert.equal(state(), null);
});
