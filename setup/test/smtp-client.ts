// Separate process: Node loads the test CA at startup, never disabling TLS checks.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { AuthStore } from "../server/utils/auth.ts";

const mode = process.argv[2]!;
const root = process.env.SMTP_TEST_ROOT!;
const state = path.join(root, mode);
const store = new AuthStore(state);
const settings = { host: "127.0.0.1", port: Number(process.env.SMTP_TEST_PORT),
  secure: mode !== "plaintext", user: "", password: "", from: "admin@example.invalid" };
if (mode !== "trusted") {
  await assert.rejects(store.configureEmail("owner@example.invalid", settings), /Email delivery failed/);
  const account = JSON.parse(fs.readFileSync(path.join(state, "secrets/admin.json"), "utf8"));
  assert.equal(account.email, "");
  assert.equal(account.verified, false);
} else {
  const initial = fs.readFileSync(path.join(state, "secrets/initial-password"), "utf8").trim();
  const first = store.login("admin", initial, "fixture");
  store.changePassword(first.id, initial, "test-new-administrator-password");
  const session = store.login("admin", "test-new-administrator-password", "fixture");
  await store.configureEmail("owner@example.invalid", settings);
  const verification = fs.readFileSync(path.join(root, "delivered.txt"), "utf8");
  assert.match(verification, /Subject: Verify Elderbrain recovery email/);
  store.verifyEmail(/Verification code: (\d+)/.exec(verification)![1]!);
  assert.equal(store.authorize(session.id).ready, true);
  await store.requestRecovery("owner@example.invalid", "fixture");
  const recovery = fs.readFileSync(path.join(root, "delivered.txt"), "utf8");
  const token = /Recovery token: ([A-Za-z0-9_-]+)/.exec(recovery)![1]!;
  store.resetPassword(token, "test-recovered-administrator-password", "fixture");
  assert.equal(store.session(session.id).authenticated, false);
  assert.equal(store.login("admin", "test-recovered-administrator-password", "fixture").ready, true);
}
