import test, { type TestContext } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { beamerStatus, readBeamer, saveBeamer, removeBeamer } from "../server/utils/beamer.ts";

const input = { worldId: "test-world", userId: "AbCdEf0123456789", password: "test-only-beamer-password" };
test("username pairing defaults to Beamer and retains legacy ID compatibility", t => {
  const file = fixture(t);
  saveBeamer(file, { worldId: input.worldId, password: input.password });
  assert.equal(readBeamer(file)?.username, "Beamer");
  assert.equal(readBeamer(file)?.userId, undefined);
  saveBeamer(file, { worldId: input.worldId, username: "Projector Player", password: input.password });
  assert.equal(beamerStatus(file).username, "Projector Player");
  for (const username of ["", "  ", "bad\nname", "a".repeat(129), 7])
    assert.throws(() => saveBeamer(file, { ...input, username }));
  saveBeamer(file, input);
  assert.equal(readBeamer(file)?.userId, input.userId);
});
function fixture(t: TestContext) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "elderbrain-beamer-store-"));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  return path.join(directory, "secrets", "beamer.json");
}
test("Beamer storage is private and never claims verified login", t => {
  const file = fixture(t);
  assert.equal(beamerStatus(file).state, "pairing-required");
  const status = saveBeamer(file, input);
  assert.equal(status.state, "pending-verification");
  assert.equal(JSON.stringify(status).includes(input.password), false);
  assert.equal(fs.statSync(file).mode & 0o777, 0o600);
  assert.equal(readBeamer(file)?.password, input.password);
  const revision = readBeamer(file)?.revision;
  saveBeamer(file, input);
  assert.notEqual(readBeamer(file)?.revision, revision);
  assert.equal(removeBeamer(file).state, "pairing-required");
});
test("invalid Beamer input leaves existing credentials unchanged", t => {
  const file = fixture(t);
  saveBeamer(file, input);
  const before = fs.readFileSync(file);
  for (const patch of [{ worldId: "../world" }, { userId: "bad" }, { password: "short" }, { password: "secret\n".repeat(5) }]) {
    assert.throws(() => saveBeamer(file, { ...input, ...patch }));
    assert.deepEqual(fs.readFileSync(file), before);
  }
});
test("unsafe or corrupt Beamer records fail closed without secret diagnostics", t => {
  const file = fixture(t);
  saveBeamer(file, input);
  fs.chmodSync(file, 0o644);
  assert.throws(() => readBeamer(file), /^Error: Stored Beamer configuration is unavailable$/);
  fs.chmodSync(file, 0o600);
  fs.writeFileSync(file, input.password);
  assert.throws(() => readBeamer(file), /^Error: Stored Beamer configuration is unavailable$/);
  fs.unlinkSync(file);
  fs.symlinkSync('/etc/passwd', file);
  assert.throws(() => readBeamer(file), /^Error: Stored Beamer configuration is unavailable$/);
});
