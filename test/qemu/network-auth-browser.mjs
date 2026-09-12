// Actual installed UI and TLS; no endpoint mocks or certificate exceptions.
import assert from 'node:assert/strict';
import readline from 'node:readline';
import { setTimeout as delay } from 'node:timers/promises';
import { chromium } from '/opt/mindflayer-elderbrain/beamer/node_modules/playwright-core/index.mjs';

const lines = readline.createInterface({ input: process.stdin });
const iterator = lines[Symbol.asyncIterator]();
const { password } = JSON.parse((await iterator.next()).value);
let browser, stage = 'launch';
try {
  browser = await chromium.launch({ executablePath: '/usr/bin/google-chrome-stable', chromiumSandbox: true });
  const context = await browser.newContext();
  const page = await context.newPage();
  page.setDefaultTimeout(10000);
  async function login(target) {
    stage = 'login-heading';
    await target.getByRole('heading', { name: 'Sign in to Elderbrain', exact: true }).waitFor();
    stage = 'login-password-field';
    await target.getByLabel('Administrator password', { exact: true }).fill(password);
    stage = 'login-submit';
    await target.getByRole('button', { name: 'Sign in', exact: true }).click();
    stage = 'login-navigation';
    await target.getByRole('navigation', { name: 'Administration' }).waitFor();
  }
  stage = 'old-address-login';
  await page.goto('https://10.0.2.15/elderbrain/network');
  await login(page);
  stage = 'old-address-login';
  const oldSession = await page.evaluate(async () => (await fetch('/elderbrain/api/auth/session')).json());
  assert.equal(oldSession.ready, true);
  const oldCookie = (await context.cookies('https://10.0.2.15')).find(cookie => cookie.name === 'elderbrain-session');
  assert.ok(oldCookie?.secure && oldCookie.httpOnly && oldCookie.sameSite === 'Strict');
  stage = 'form-apply';
  await page.getByRole('combobox', { name: 'Network interface', exact: true }).click();
  await page.getByRole('option', { name: 'ens3', exact: true }).click();
  await page.getByRole('combobox', { name: 'IPv4 mode', exact: true }).click();
  await page.getByRole('option', { name: 'Manual (static IPv4)', exact: true }).click();
  await page.getByLabel('IPv4 address', { exact: true }).fill('10.0.2.20');
  await page.getByLabel('Gateway', { exact: true }).fill('10.0.2.2');
  await page.getByLabel('IPv4 DNS servers', { exact: true }).fill('10.0.2.3');
  await page.getByRole('button', { name: 'Apply with timed rollback' }).click();
  await page.getByRole('button', { name: 'Confirm through new address' }).waitFor();
  console.log('capture-required');
  assert.equal((await iterator.next()).value, 'captured');
  stage = 'new-address-tls';
  const check = await context.newPage();
  let available = false;
  for (let attempt = 0; attempt < 15; attempt++) {
    try {
      const response = await check.goto('https://10.0.2.20:10444/', { timeout: 1500 });
      if (response.status() === 200) { available = true; break; }
    } catch { /* Only retry liveness; never retry a mutation. */ }
    await delay(500);
  }
  assert.ok(available);
  await check.close();
  stage = 'old-page-confirmation';
  await page.getByRole('button', { name: 'Confirm through new address' }).click();
  await page.getByText('Network configuration confirmed', { exact: true }).waitFor();
  stage = 'new-address-session';
  assert.equal((await context.cookies('https://10.0.2.20')).some(cookie => cookie.name === 'elderbrain-session'), false);
  const next = await context.newPage();
  next.setDefaultTimeout(10000);
  await next.goto('https://10.0.2.20/elderbrain/network');
  assert.equal(await next.evaluate(async () => (await fetch('/elderbrain/api/config')).status), 401);
  await login(next);
  stage = 'new-address-session';
  const newSession = await next.evaluate(async () => (await fetch('/elderbrain/api/auth/session')).json());
  assert.equal(newSession.ready, true);
  assert.notEqual(newSession.csrf, oldSession.csrf);
  assert.equal(await next.evaluate(async csrf => (await fetch('/elderbrain/api/auth/logout', {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'x-elderbrain-request': '1', 'x-csrf-token': csrf }, body: '{}',
  })).status, oldSession.csrf), 403);
  await next.getByRole('button', { name: 'Sign out', exact: true }).click();
  await next.getByRole('heading', { name: 'Sign in to Elderbrain', exact: true }).waitFor();
  console.log('passed');
} catch {
  console.log('failed:' + stage);
  process.exitCode = 1;
} finally {
  await browser?.close();
  lines.close();
}
