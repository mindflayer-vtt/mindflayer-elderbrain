// Disposable VM, executed as the existing kiosk user. No certificate overrides.
// Private transaction capability arrives on stdin, never through argv or URLs.
import assert from 'node:assert/strict';
import { chromium } from '/opt/mindflayer-elderbrain/beamer/node_modules/playwright-core/index.mjs';

let input = '';
for await (const chunk of process.stdin) {
  input += chunk;
  if (input.length > 8192) throw new Error('Test packet too large');
}
const packet = JSON.parse(input);
input = '';
const address = packet.address ?? '10.0.2.15';
assert.ok(['10.0.2.15', '10.0.2.20'].includes(address));
assert.notEqual(process.getuid(), 0);
const browser = await chromium.launch({ executablePath: '/usr/bin/google-chrome-stable', chromiumSandbox: true });
try {
  const page = await browser.newPage();
  const response = await page.goto(`https://${address}/elderbrain/`, { waitUntil: 'domcontentloaded' });
  assert.equal(response.status(), 200);
  assert.equal(await page.evaluate(() => window.isSecureContext), true);
  assert.equal(await page.evaluate(async () => (await fetch('/elderbrain/api/config')).status), 401);
  const wrongName = await browser.newPage();
  await assert.rejects(wrongName.goto('https://127.0.0.2/elderbrain/'), /ERR_CERT_COMMON_NAME_INVALID/);
  await wrongName.close();
  const result = await page.evaluate(async ({ id, token, address }) => {
    async function confirm(value) {
      const response = await fetch(`https://${address}:10444/confirm`, {
        method: 'POST', credentials: 'omit', redirect: 'error',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id, token: value }),
        signal: AbortSignal.timeout(10000),
      });
      return { status: response.status, body: await response.json(), type: response.type };
    }
    const rejected = await confirm((token[0] === 'A' ? 'B' : 'A') + token.slice(1));
    const accepted = await confirm(token);
    return { rejected, accepted };
  }, { id: packet.id, token: packet.token, address });
  assert.equal(result.rejected.status, 409);
  assert.equal(result.rejected.type, 'cors');
  assert.equal(result.accepted.status, 200);
  assert.equal(result.accepted.type, 'cors');
  assert.equal(result.accepted.body.phase, 'confirmed');
  console.log('PASS: kiosk Chromium trusts the installed CA, rejects wrong-IP TLS, and confirms without certificate exceptions.');
} finally {
  await browser.close();
}
