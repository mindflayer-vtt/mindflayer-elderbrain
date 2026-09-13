import test from "node:test";
import assert from "node:assert/strict";
import { installationRecovery } from "../shared/installation-recovery.ts";

test("installation recovery distinguishes pre-write, partial flash and online failures", () => {
  for (const stage of ["preflight", "backup-provisioning", "prepare-provisioning", "register-credential"]) {
    assert.match(installationRecovery(stage).join(" "), /[Nn]o firmware write has started|Firmware writing has not started/);
  }
  assert.match(installationRecovery("register-credential").join(" "), /credential may already exist/);
  assert.match(installationRecovery("flash-firmware").join(" "), /Firmware may be incomplete/);
  assert.match(installationRecovery("serial-provisioning").join(" "), /may or may not have been accepted/);
  assert.match(installationRecovery("serial-provisioning", false).join(" "), /Firmware was not changed/);
  assert.doesNotMatch(installationRecovery("serial-provisioning", false).join(" "), /Firmware was written/);
  assert.match(installationRecovery("verify-online").join(" "), /do not immediately reflash/);
  assert.match(installationRecovery().join(" "), /last safe stage is unknown/);
  assert.deepEqual(installationRecovery("private-secret"), installationRecovery());
});
