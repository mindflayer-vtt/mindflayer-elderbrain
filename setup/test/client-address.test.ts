import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { clientAddress } from "../server/utils/client-address.ts";
import { AuthError, AuthStore } from "../server/utils/auth.ts";

test("trusted proxy identifies distinct clients from the authoritative rightmost address", () => {
  assert.equal(clientAddress("172.31.254.2", "192.0.2.10", false, "172.31.254.2"), "proxy:192.0.2.10");
  assert.equal(clientAddress("::ffff:172.31.254.2", "2001:db8::20", false, "172.31.254.2"), "proxy:2001:db8::20");
  assert.equal(clientAddress("172.31.254.2", "198.51.100.99, 192.0.2.10", false, "172.31.254.2"),
    "proxy:192.0.2.10", "a spoofed leading value must not become authoritative");
});

test("production rejects untrusted, missing and malformed forwarding metadata", () => {
  for (const invoke of [
    () => clientAddress("172.31.254.3", "192.0.2.10", false, "172.31.254.2"),
    () => clientAddress("172.31.254.2", undefined, false, "172.31.254.2"),
    () => clientAddress("172.31.254.2", "garbage, 192.0.2.10", false, "172.31.254.2"),
    () => clientAddress("172.31.254.2", "192.0.2.10:1234", false, "172.31.254.2"),
  ]) assert.throws(invoke, (error) => error instanceof AuthError && [400, 403].includes(error.statusCode));
});

test("direct development mode uses only the socket peer", () => {
  assert.equal(clientAddress("127.0.0.1", "198.51.100.99", true), "direct:127.0.0.1");
});

test("per-client throttling remains isolated while the global limit spans clients", () => {
  const state = fs.mkdtempSync(path.join(os.tmpdir(), "elderbrain-client-rate-"));
  const store = new AuthStore(state);
  for (let attempt = 0; attempt < 10; attempt++)
    assert.throws(() => store.login("admin", "wrong-password", "proxy:192.0.2.1"), /Invalid/);
  assert.throws(() => store.login("admin", "wrong-password", "proxy:192.0.2.1"),
    (error) => error instanceof AuthError && error.statusCode === 429);
  assert.throws(() => store.login("admin", "wrong-password", "proxy:192.0.2.200"), /Invalid/,
    "one exhausted client must not lock another client");
  for (let attempt = 11; attempt < 60; attempt++)
    assert.throws(() => store.login("admin", "wrong-password", `proxy:198.51.100.${attempt}`), /Invalid/);
  assert.throws(() => store.login("admin", "wrong-password", "proxy:203.0.113.1"),
    (error) => error instanceof AuthError && error.statusCode === 429,
    "global throttling must still apply across clients");
});
