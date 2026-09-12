import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { AuthStore, AuthError, passwordHash, bootstrapPassword, offlineRecoveryCode } from "../server/utils/auth.ts";
import bootstrapWords from "../shared/bootstrap-words.json";

test("bootstrap passphrases have eight independently selected words", () => {
  assert.equal(bootstrapWords.length, 256);
  assert.equal(new Set(bootstrapWords).size, 256);
  assert.ok(bootstrapWords.every(word => /^[a-z]{3,8}$/.test(word)));
  const samples = Array.from({ length: 100 }, bootstrapPassword);
  assert.equal(new Set(samples).size, 100);
  for (const value of samples) {
    assert.equal(value.split("-").length, 8);
    assert.ok(value.split("-").every(word => bootstrapWords.includes(word)));
    assert.ok(value.length >= 24 && value.length <= 256);
  }
});

test("offline recovery codes use sixteen lowercase words", () => {
  const samples = Array.from({ length: 100 }, offlineRecoveryCode);
  assert.equal(new Set(samples).size, 100);
  for (const code of samples) {
    assert.equal(code.split("-").length, 16);
    assert.ok(code.split("-").every(word => bootstrapWords.includes(word)));
    assert.ok(code.length <= 256);
  }
});

test("existing bootstrap credentials survive a restart unchanged", (t) => {
  const { state, initial } = fixture(t);
  const store = new AuthStore(state);
  assert.equal(fs.readFileSync(path.join(state, "secrets/initial-password"), "utf8").trim(), initial);
  assert.equal(store.login("admin", initial, "local").mustChange, true);
});

function fixture(t: { after: (fn: () => void) => void }) {
  const state = fs.mkdtempSync(path.join(os.tmpdir(), "elderbrain-auth-"));
  t.after(() => fs.rmSync(state, { recursive: true, force: true }));
  const mail: string[] = [];
  const store = new AuthStore(state, async (_settings, _to, _subject, text) => { mail.push(text); });
  const initial = fs.readFileSync(path.join(state, "secrets/initial-password"), "utf8").trim();
  return { state, store, initial, mail };
}
const smtp = { host: "smtp.example.com", port: 587, secure: false, user: "admin", password: "secret", from: "admin@example.com" };

test("file SMTP defaults stay private, are optional, and custom settings override them", async (t) => {
  const { state, store, initial, mail } = fixture(t);
  const file = path.join(state, "secrets/default-smtp.json");
  await assert.rejects(store.configureEmail("owner@example.com", undefined), /SMTP settings required/);
  fs.writeFileSync(file, JSON.stringify(smtp), { mode: 0o600 });
  const session = store.login("admin", initial, "local");
  assert.equal(session.defaultSmtpAvailable, true);
  assert.ok(!JSON.stringify(session).includes(smtp.host));
  assert.ok(!JSON.stringify(store.session()).includes("defaultSmtpAvailable"));
  await store.configureEmail("owner@example.com", undefined);
  assert.equal(mail.length, 1);
  assert.equal(JSON.parse(fs.readFileSync(path.join(state, "secrets/admin.json"), "utf8")).smtp.host, smtp.host);
  await store.configureEmail("owner@example.com", { ...smtp, host: "custom.example.com" });
  assert.equal(JSON.parse(fs.readFileSync(path.join(state, "secrets/admin.json"), "utf8")).smtp.host, "custom.example.com");
  fs.writeFileSync(file, "invalid JSON");
  await assert.rejects(store.configureEmail("owner@example.com", undefined), /Default SMTP configuration/);
});

test("interrupted bootstrap files never create an empty-password account", (t) => {
  const state = fs.mkdtempSync(path.join(os.tmpdir(), "elderbrain-auth-interrupted-"));
  t.after(() => fs.rmSync(state, { recursive: true, force: true }));
  fs.mkdirSync(path.join(state, "secrets"));
  fs.writeFileSync(path.join(state, "secrets/initial-password"), "");
  const store = new AuthStore(state);
  const initial = fs.readFileSync(path.join(state, "secrets/initial-password"), "utf8").trim();
  assert.ok(initial.length >= 24);
  assert.throws(() => store.login("admin", "", "test"), /Invalid/);
  assert.equal(store.login("admin", initial, "test").mustChange, true);
  fs.writeFileSync(path.join(state, "secrets/initial-password"), "");
  fs.writeFileSync(path.join(state, "secrets/admin-reset.request"), "");
  assert.throws(() => store.login("admin", "", "test"), /incomplete/);
});

test("a legacy empty-password hash cannot authenticate", (t) => {
  const { state } = fixture(t);
  fs.writeFileSync(path.join(state, "secrets/admin.json"), JSON.stringify({ schema: 1,
    password: passwordHash(""), mustChange: true, email: "", verified: false }));
  const store = new AuthStore(state);
  for (const value of ["", undefined, null, 0]) assert.throws(() => store.login("admin", value, "test"), /Invalid/);
});

test("bootstrap is unique, stored privately and never sufficient for administrative access", (t) => {
  const { store, state, initial } = fixture(t);
  assert.ok(initial.length >= 24);
  const session = store.login("admin", initial, "local");
  assert.equal(session.mustChange, true);
  assert.equal(session.ready, false);
  assert.throws(() => store.authorize(session.id), /Complete first-login/);
  assert.throws(() => store.authorize(session.id, "wrong", true, true), /CSRF/);
  assert.throws(() => store.login("someone", initial, "local"), /Invalid/);
  const account = fs.readFileSync(path.join(state, "secrets/admin.json"), "utf8");
  assert.ok(!account.includes(initial));
  assert.equal(fs.statSync(path.join(state, "secrets/admin.json")).mode & 0o777, 0o600);
  assert.equal(fs.statSync(path.join(state, "secrets/initial-password")).mode & 0o777, 0o600);
});

test("password change and verified recovery email unlock administration; recovery revokes sessions", async (t) => {
  const { store, state, initial, mail } = fixture(t);
  const first = store.login("admin", initial, "local");
  assert.throws(() => store.changePassword(first.id, initial, "short"), /12/);
  store.changePassword(first.id, initial, "my-new-long-password");
  assert.equal(store.session(first.id).authenticated, false);
  assert.equal(fs.existsSync(path.join(state, "secrets/initial-password")), false);
  const second = store.login("admin", "my-new-long-password", "local");
  assert.equal(second.ready, false);
  await store.configureEmail("owner@example.com", smtp);
  assert.throws(() => store.verifyEmail("wrong"), /Incorrect/);
  const code = /Verification code: (\d+)/.exec(mail[0]!)![1]!;
  const recovery = store.verifyEmail(code);
  assert.equal(recovery.split("-").length, 16);
  assert.ok(!fs.readFileSync(path.join(state, "secrets/admin.json"), "utf8").includes(recovery));
  assert.equal(store.authorize(second.id, second.csrf, true).ready, true);
  assert.throws(() => store.verifyEmail(code), /expired/);
  store.resetPassword(recovery, "recovered-long-password", "local");
  assert.equal(store.session(second.id).authenticated, false);
  assert.throws(() => store.resetPassword(recovery, "another-long-password", "local"), /Invalid/);
  assert.equal(store.login("admin", "recovered-long-password", "local").ready, true);
});

test("email recovery avoids sending to unknown addresses and tokens work once", async (t) => {
  const { store, mail } = fixture(t);
  await store.configureEmail("owner@example.com", smtp);
  store.verifyEmail(/Verification code: (\d+)/.exec(mail[0]!)![1]!);
  await store.requestRecovery("stranger@example.com", "local");
  assert.equal(mail.length, 1);
  await store.requestRecovery("owner@example.com", "local");
  const token = /Recovery token: (\S+)/.exec(mail[1]!)![1]!;
  store.resetPassword(token, "email-recovered-password", "local");
  assert.throws(() => store.resetPassword(token, "email-recovered-password", "local"), /Invalid/);
});

test("failed delivery does not change recovery configuration; login throttles", async (t) => {
  const { store, state, initial } = fixture(t);
  const failing = new AuthStore(state, async () => { throw new Error("SMTP unavailable"); });
  await assert.rejects(failing.configureEmail("owner@example.com", smtp));
  assert.equal(failing.login("admin", initial, "local").email, "");
  for (let i = 0; i < 10; i++) assert.throws(() => store.login("admin", "wrong", "attacker"), /Invalid/);
  assert.throws(() => store.login("admin", initial, "attacker"), (e) => e instanceof AuthError && e.statusCode === 429);
});

test("root reset invalidates sessions and forces another password change", (t) => {
  const { store, state, initial } = fixture(t);
  const session = store.login("admin", initial, "local");
  fs.writeFileSync(path.join(state, "secrets/initial-password"), "root-generated-temporary-password", { mode: 0o600 });
  fs.writeFileSync(path.join(state, "secrets/admin-reset.request"), "", { mode: 0o600 });
  assert.equal(store.session(session.id).authenticated, false);
  assert.equal(store.login("admin", "root-generated-temporary-password", "local").mustChange, true);
});
