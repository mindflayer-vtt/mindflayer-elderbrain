"""Optional published-image check; no host mounts, ports or physical devices.

Set ELDERBRAIN_TEST_SERVER_IMAGE to an already-pulled tag@sha256 reference.
The isolated container and its anonymous data volume are removed after the test.
"""
import base64
import json
import os
import subprocess
import time
import unittest


@unittest.skipUnless(os.environ.get("ELDERBRAIN_TEST_SERVER_IMAGE"), "published image integration is opt-in")
class ServerImageTests(unittest.TestCase):
    def test_private_installation_commands_and_authenticated_proof(self):
        image = os.environ["ELDERBRAIN_TEST_SERVER_IMAGE"]
        self.assertRegex(image, r"^mindflayervtt/server:[0-9]+\.[0-9]+\.[0-9]+@sha256:[a-f0-9]{64}$")
        started = subprocess.run(["docker", "run", "--pull=never", "--rm", "--detach", "--network", "none",
                                  "--env", "MINDFLAYER_FIRMWARE_AUTO_UPDATE=false", image],
                                 check=True, capture_output=True, text=True, timeout=30)
        container = started.stdout.strip()
        self.assertRegex(container, r"^[a-f0-9]{64}$")
        self.addCleanup(lambda: subprocess.run(["docker", "rm", "--force", container],
                                              check=True, capture_output=True, timeout=30))

        def execute(arguments, payload=None, timeout=20):
            result = subprocess.run(["docker", "exec", "-i", container, "node", *arguments],
                                    input=json.dumps(payload) if payload is not None else "",
                                    capture_output=True, text=True, timeout=timeout)
            # Never include private command output in assertion failures.
            diagnostic = next((line for line in result.stderr.splitlines() if line in
                               ("CHECK_EAGAIN", "CHECK_AUTH", "CHECK_VERIFY_EXIT", "CHECK_VERIFY_RESULT", "CHECK_TIMEOUT", "CHECK_SOCKET", "CHECK_OTHER")), "unclassified")
            self.assertEqual(result.returncode, 0, "Private container command failed: " + diagnostic)
            return result.stdout

        deadline = time.monotonic() + 30
        while True:
            probe = subprocess.run(["docker", "exec", container, "node", "scripts/healthcheck.js"],
                                   capture_output=True, timeout=6)
            if probe.returncode == 0:
                break
            if time.monotonic() >= deadline:
                self.fail("Isolated server did not become healthy")
            time.sleep(0.5)
        capabilities = json.loads(execute(["scripts/installation-capabilities.js"]))
        self.assertIn(3, capabilities["deviceProtocolVersions"])
        self.assertEqual(capabilities["configurationProof"], "sha256-canonical-envelope-v2")
        sector = base64.b64encode(b"\xff" * 4096).decode()
        plan = json.loads(execute(["scripts/prepare-installation.js"], {
            "sectorA": sector, "sectorB": sector, "adopt": False,
            "settings": {"ssid": "Isolated test", "psk": "isolated-test-password", "serverHost": "table.local", "serverPort": 10443},
        }))
        self.assertEqual(plan["action"], "initial")
        registered = json.loads(execute(["scripts/register-installation.js"], plan["newCredential"]))
        self.assertEqual(registered, {"id": plan["deviceId"], "state": "registered"})
        # Repeat registration is idempotent and must not require a server restart.
        self.assertEqual(json.loads(execute(["scripts/register-installation.js"], plan["newCredential"])), registered)
        proof = execute(["-e", r'''
const fs = require('node:fs');
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const WebSocket = require('ws');
const cbor = require('cbor');
const { calculateHmacBytes } = require('./src/security/device-auth');
let stage = 'OTHER';
process.on('uncaughtException', error => {
  process.stderr.write(error.code === 'EAGAIN' ? 'CHECK_EAGAIN\n' : 'CHECK_' + stage + '\n');
  process.exit(1);
});
const plan = JSON.parse(fs.readFileSync(0, 'utf8'));
const timeout = setTimeout(() => { process.stderr.write('CHECK_TIMEOUT\n'); process.exit(1); }, 15000);
const notBefore = Date.now();
const device = new WebSocket('wss://127.0.0.1:10443/device/v1', { rejectUnauthorized: false });
device.on('error', () => { process.stderr.write('CHECK_SOCKET\n'); process.exit(1); });
device.on('message', data => {
  const frame = cbor.decodeFirstSync(data);
  if (frame[0] === 0) device.send(cbor.encodeCanonical([1, 3, plan.deviceId,
    calculateHmacBytes(Buffer.from(plan.newCredential.secret, 'hex'), plan.deviceId, frame[2])]));
  if (frame[0] === 2) {
    stage = 'AUTH';
    assert.equal(frame[2], 0);
    device.send(cbor.encodeCanonical([3, 3, '1.2.3', 'mindflayer-keypad-v1']));
  }
  if (frame[0] === 8) {
    device.send(cbor.encodeCanonical([9, 3, frame[3], Buffer.from(plan.configurationDigest, 'hex')]));
    const verify = spawn(process.execPath, ['scripts/verify-installation.js'], { stdio: ['pipe', 'pipe', 'pipe'] });
    let output = '';
    verify.stdout.on('data', chunk => { output += chunk; if (output.length > 16384) process.exit(1); });
    verify.stderr.resume();
    verify.on('error', () => process.exit(1));
    verify.on('exit', code => {
      stage = 'VERIFY_EXIT';
      assert.equal(code, 0);
      stage = 'VERIFY_RESULT';
      const result = JSON.parse(output);
      assert.equal(result.id, plan.deviceId);
      assert.equal(result.deviceAuthenticated, true);
      assert.equal(result.configurationDigest, plan.configurationDigest);
      assert.equal(result.firmware, '1.2.3');
      assert.ok(result.configurationVerifiedAt >= notBefore);
      device.terminate(); clearTimeout(timeout);
      process.stdout.write(JSON.stringify({ verified: true }));
    });
    verify.stdin.end(JSON.stringify({ id: plan.deviceId, firmware: '1.2.3', digest: plan.configurationDigest, notBefore }));
  }
});
'''], plan, timeout=25)
        self.assertEqual(json.loads(proof), {"verified": True})


if __name__ == "__main__":
    unittest.main()
