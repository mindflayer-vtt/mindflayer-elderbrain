// Invoked by network-external.py --browser. Credentials arrive only on stdin.
// CONNECT changes routing, not TLS or HTTP: both endpoints remain the real VM.
import assert from 'node:assert/strict';
import { createHash, X509Certificate } from 'node:crypto';
import http from 'node:http';
import net from 'node:net';
import { chromium } from '../../setup/node_modules/playwright-core/index.mjs';

let input = '';
for await (const chunk of process.stdin) input += chunk;
const packet = JSON.parse(input);
input = '';
const address = packet.address ?? '10.0.2.15';
assert.ok(['10.0.2.15', '10.0.2.20'].includes(address));
const confirmationURL = `https://${address}:10444/confirm`;
const pins = packet.certificates.map(pem => createHash('sha256')
  .update(new X509Certificate(pem).publicKey.export({ type: 'spki', format: 'der' }))
  .digest('base64')).join(',');
const sockets = new Set();
const proxy = http.createServer((_request, response) => response.writeHead(403).end());
proxy.on('connect', (request, client, head) => {
  const port = { [`${address}:443`]: 24443, [`${address}:10444`]: 24444 }[request.url];
  if (!port) return client.destroy();
  const upstream = net.connect(port, '127.0.0.1', () => {
    client.write('HTTP/1.1 200 Connection Established\r\n\r\n');
    if (head.length) upstream.write(head);
    upstream.pipe(client);
    client.pipe(upstream);
  });
  sockets.add(upstream);
  upstream.on('close', () => sockets.delete(upstream));
  upstream.on('error', () => client.destroy());
  client.on('error', () => upstream.destroy());
  client.on('close', () => upstream.destroy());
});
proxy.on('connection', socket => {
  sockets.add(socket);
  socket.on('close', () => sockets.delete(socket));
});
await new Promise(resolve => proxy.listen(0, '127.0.0.1', resolve));
let browser;
try {
  browser = await chromium.launch({
    proxy: { server: `http://127.0.0.1:${proxy.address().port}` },
    args: [`--ignore-certificate-errors-spki-list=${pins}`],
  });
  const page = await browser.newPage();
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Network.enable');
  let preflight = false;
  cdp.on('Network.requestWillBeSent', event => {
    if (event.request.url === confirmationURL
        && event.request.method === 'OPTIONS') preflight = true;
  });
  const response = await page.goto(`https://${address}/elderbrain/`, { waitUntil: 'domcontentloaded' });
  assert.equal(response.status(), 200);
  assert.equal(await page.evaluate(() => window.isSecureContext), true);
  const rejected = await page.evaluate(async ({ id, token, confirmationURL }) => {
    const response = await fetch(confirmationURL, {
      method: 'POST', credentials: 'omit', redirect: 'error',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id, token: (token[0] === 'A' ? 'B' : 'A') + token.slice(1) }),
      signal: AbortSignal.timeout(10000),
    });
    return { status: response.status, type: response.type };
  }, { id: packet.id, token: packet.token, confirmationURL });
  assert.equal(rejected.status, 409);
  assert.equal(rejected.type, 'cors');
  const result = await page.evaluate(async ({ id, token, confirmationURL }) => {
    const response = await fetch(confirmationURL, {
      method: 'POST', credentials: 'omit', redirect: 'error',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id, token }),
      signal: AbortSignal.timeout(10000),
    });
    return { status: response.status, body: await response.json(), type: response.type };
  }, { id: packet.id, token: packet.token, confirmationURL });
  assert.equal(result.status, 200);
  assert.equal(result.type, 'cors');
  assert.equal(result.body.phase, 'confirmed');
  assert.equal(preflight, true);
  console.log('PASS: real browser cross-origin confirmation and preflight.');
} finally {
  await browser?.close();
  for (const socket of sockets) socket.destroy();
  await new Promise(resolve => proxy.close(resolve));
}
