// Disposable VM only. Input contains private credentials; output never does.
import fs from 'node:fs';
import https from 'node:https';
import { setTimeout as delay } from 'node:timers/promises';

let input = '';
for await (const chunk of process.stdin) { input += chunk; if (input.length > 8192) throw new Error('Test input too large'); }
const values = JSON.parse(input);
const ca = fs.readFileSync('/var/lib/mindflayer-elderbrain/traefik/tls/ca.crt');
let cookie = '', csrf = '';
let previewId, pairingOwned = false;
async function api(route, method = 'GET', body) {
  const data = body === undefined ? undefined : JSON.stringify(body);
  return await new Promise((resolve, reject) => {
    const request = https.request({ hostname: '127.0.0.1', port: 443, path: '/elderbrain/api/' + route,
      method, ca, headers: { cookie, 'x-elderbrain-request': '1', 'x-csrf-token': csrf,
        ...(data === undefined ? {} : { 'content-type': 'application/json', 'content-length': Buffer.byteLength(data) }) } }, response => {
      let text = '';
      response.on('data', chunk => { text += chunk; });
      response.on('end', () => {
        if (response.statusCode < 200 || response.statusCode >= 300) return reject(new Error('API test request failed'));
        if (response.headers['set-cookie']) cookie = response.headers['set-cookie'].map(item => item.split(';')[0]).join('; ');
        try { resolve(JSON.parse(text)); } catch { reject(new Error('Invalid API response')); }
      });
    });
    request.setTimeout(30000, () => request.destroy(new Error('Request timed out')));
    request.on('error', () => reject(new Error('Verified HTTPS request failed')));
    request.end(data);
  });
}

try {
  const session = await api('auth/login', 'POST', { username: 'admin', password: values.password });
  if (!session.ready) throw new Error('Fixture account is not ready');
  csrf = session.csrf;
  const status = await api('foundry/beamer');
  if (status.state !== 'pairing-required') throw new Error('Unexpected pre-existing pairing');
  console.log('PASS: certificate-verified HTTPS login and authenticated Beamer status on the installed VM.');
  if (values.beamer) {
    if (values.beamer.worldId !== 'elderbrain-beamer') throw new Error('Not the disposable world');
    const config = await api('config');
    const existing = await api('display-preview');
    if (['pending', 'committing', 'rolling-back'].includes(existing.phase)) throw new Error('Existing preview must not be replaced');
    pairingOwned = true;
    await api('foundry/beamer', 'PUT', values.beamer);
    const preview = await api('display-preview', 'POST', { ...config, configured: true,
      views: [{ output: '', url: 'http://foundry.elderbrain.local', mode: 'player', tabs: [] }] });
    previewId = preview.id;
    if (!previewId) throw new Error('Preview identifier missing');
    const deadline = Date.now() + 65000;
    let ready = false;
    while (Date.now() < deadline) {
      const current = await api('foundry/beamer');
      if (JSON.stringify(current).includes(values.beamer.password)) throw new Error('Private credential in public status');
      if (current.state === 'ready' && current.views?.some(view => view.index === 0 && view.state === 'ready')) {
        ready = true; break;
      }
      await delay(2000);
    }
    if (!ready) throw new Error('Automatic view did not become ready');
    console.log('PASS: authenticated save, root projection, automatic launcher and live ready status.');
  }
} catch {
  console.error('VM API fixture failed; private diagnostics suppressed.');
  process.exitCode = 1;
} finally {
  if (previewId) {
    try {
      const current = await api('display-preview');
      if (current.id === previewId && current.phase === 'pending') await api('display-preview/cancel', 'POST', { id: previewId });
      else if (current.id !== previewId || current.phase !== 'rolled-back') throw new Error('Unexpected preview cleanup state');
    } catch { process.exitCode = 1; }
  }
  if (pairingOwned) {
    try {
      const current = await api('foundry/beamer');
      if (current.userId !== values.beamer.userId) throw new Error('Pairing ownership changed');
      await api('foundry/beamer', 'DELETE');
      if ((await api('foundry/beamer')).state !== 'pairing-required') throw new Error('Pairing cleanup failed');
      console.log('PASS: test pairing removed and display preview reverted.');
    } catch { process.exitCode = 1; }
  }
  if (csrf) await api('auth/logout', 'POST', {}).catch(() => { process.exitCode = 1; });
}
