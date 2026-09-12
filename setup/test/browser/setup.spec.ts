import { test, expect, type BrowserContext } from "@playwright/test";
let cookies: Awaited<ReturnType<BrowserContext["cookies"]>>;
test.beforeAll(async ({ playwright, baseURL }) => {
  const request = await playwright.request.newContext({ baseURL });
  const response = await request.post("/elderbrain/api/auth/login", {
    headers: { "x-elderbrain-request": "1" },
    data: { username: "admin", password: "browser-test-password" },
  });
  expect(response.ok()).toBe(true);
  cookies = (await request.storageState()).cookies;
  await request.dispose();
});
test.use({ storageState: async ({}, use) => { await use({ cookies, origins: [] }); } });

test('checkpoint restore requires consent and supported components in API and UI', async ({ page, request, playwright, baseURL }) => {
  const data = { checkpoint: 'e'.repeat(32), components: ['preferences'], confirmRestore: true, confirmDowntime: true };
  const anonymous = await playwright.request.newContext({ baseURL, storageState: { cookies: [], origins: [] } });
  try { expect((await anonymous.post('/elderbrain/api/snapshots/restore', { headers: { 'x-elderbrain-request': '1' }, data })).status()).toBe(401); }
  finally { await anonymous.dispose(); }
  expect((await request.post('/elderbrain/api/snapshots/restore', { data })).status()).toBe(403);
  const session = await (await request.get('/elderbrain/api/auth/session')).json();
  const headers = { 'x-elderbrain-request': '1', 'x-csrf-token': session.csrf };
  for (const changes of [{ confirmRestore: false }, { confirmDowntime: false }, { components: ['security'] }, { checkpoint: '../data' }]) {
    expect((await request.post('/elderbrain/api/snapshots/restore', { headers, data: { ...data, ...changes } })).ok()).toBe(false);
  }
  await page.goto('/elderbrain/backups');
  const button = page.getByRole('button', { name: 'Restore selected configuration', exact: true });
  await expect(button).toBeDisabled();
  await page.getByRole('combobox', { name: 'Checkpoint to restore' }).click();
  await page.getByRole('option', { name: /eeeeeeee/ }).click();
  await page.getByRole('checkbox', { name: /^Elderbrain preferences:/ }).check();
  await page.getByRole('checkbox', { name: /^I agree to briefly pause/ }).check();
  await expect(button).toBeDisabled();
  await page.getByRole('checkbox', { name: /^Replace the selected configuration/ }).check();
  await expect(button).toBeEnabled();
  await button.click();
  await expect(page.getByText('Restore checkpoint: completed', { exact: false })).toBeVisible();
  await expect(button).toBeDisabled();
});

test('checkpoint retention requires deletion consent and persists the selected limit', async ({ page, request }) => {
  expect((await request.put('/elderbrain/api/snapshots/retention', { data: { enabled: true, keep: 3 } })).status()).toBe(403);
  const session = await (await request.get('/elderbrain/api/auth/session')).json();
  const headers = { 'x-elderbrain-request': '1', 'x-csrf-token': session.csrf };
  const denied = await request.put('/elderbrain/api/snapshots/retention', { headers, data: { enabled: true, keep: 3 } });
  expect(denied.ok()).toBe(false);
  expect(await denied.text()).toContain('Confirm automatic deletion');
  await page.goto('/elderbrain/backups');
  await page.getByRole('checkbox', { name: 'Automatically delete older unprotected checkpoints after successful captures.' }).check();
  await page.getByRole('spinbutton', { name: 'Recent checkpoints to keep' }).fill('3');
  await page.getByRole('button', { name: 'Save checkpoint retention' }).click();
  await expect(page.getByText('Retention saved.', { exact: false })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('spinbutton', { name: 'Recent checkpoints to keep' })).toHaveValue('3');
  await expect(page.getByRole('checkbox', { name: 'Automatically delete older unprotected checkpoints after successful captures.' })).toBeChecked();
});

test('checkpoint API requires authentication, CSRF and explicit downtime consent', async ({ request, playwright, baseURL }) => {
  const anonymous = await playwright.request.newContext({ baseURL, storageState: { cookies: [], origins: [] } });
  try { expect((await anonymous.get('/elderbrain/api/snapshots')).status()).toBe(401); }
  finally { await anonymous.dispose(); }
  expect((await request.post('/elderbrain/api/snapshots', { data: { confirmDowntime: true } })).status()).toBe(403);
  expect((await request.post('/elderbrain/api/snapshots', { headers: { 'x-elderbrain-request': '1' }, data: { confirmDowntime: true } })).status()).toBe(403);
  const session = await (await request.get('/elderbrain/api/auth/session')).json();
  const response = await request.post('/elderbrain/api/snapshots', { headers: { 'x-elderbrain-request': '1', 'x-csrf-token': session.csrf }, data: {} });
  expect(response.ok()).toBe(false);
  expect(await response.text()).toContain('Confirm the temporary service interruption');
});

test('local checkpoints require downtime confirmation and show persistent jobs', async ({ page }) => {
  await page.goto('/elderbrain/backups');
  await expect(page.getByRole('heading', { name: 'Local checkpoints' })).toBeVisible();
  const create = page.getByRole('button', { name: 'Create checkpoint', exact: true });
  await expect(create).toBeDisabled();
  await expect(page.getByText('e'.repeat(32), { exact: true })).toBeVisible();
  await page.getByLabel('I agree to briefly pause Foundry, Setup and display browsers.').check();
  await expect(create).toBeEnabled();
  await create.click();
  await expect(page.getByText('Create checkpoint: completed', { exact: false })).toBeVisible();
  await expect(create).toBeDisabled();
});

test('Beamer credentials stay private and live status polling preserves edits', async ({ page, request }) => {
  await page.goto('/elderbrain/foundry');
  await page.getByLabel('Foundry world ID', { exact: true }).fill('test-world');
  await expect(page.getByLabel('Beamer username', { exact: true })).toHaveValue('Beamer');
  const password = page.getByLabel('Beamer password', { exact: true });
  await password.fill('browser-private-beamer-canary');
  const form = page.locator('form').filter({ has: password });
  await form.getByRole('button', { name: 'Show password', exact: true }).click();
  await expect(password).toHaveAttribute('type', 'text');
  await form.getByRole('button', { name: 'Save for verification' }).click();
  await expect(password).toHaveValue('');
  await expect(page.getByText('Mindflayer module unavailable', { exact: true })).toBeVisible({ timeout: 10000 });
  const publicStatus = await request.get('/elderbrain/api/foundry/beamer');
  expect(await publicStatus.text()).not.toContain('browser-private-beamer-canary');
  await password.fill('another-unsaved-private-password');
  await expect(page.getByText('Screen 2: Mindflayer module unavailable')).toBeVisible();
  await page.waitForTimeout(5500);
  await expect(password).toHaveValue('another-unsaved-private-password');
  await form.getByRole('button', { name: 'Remove stored Beamer credentials' }).click();
  await expect(page.getByText('Pairing required', { exact: true })).toBeVisible();
  await expect(password).toHaveValue('');
});

test('network static settings confirm only through the new address without URL or cookie credentials', async ({ page }) => {
  let state = { phase: 'idle', id: 'a'.repeat(32), deadline: 0 };
  await page.route('**/api/network/change', async route => {
    if (route.request().method() === 'POST') {
      expect(route.request().postDataJSON()).toEqual({ interface: 'eno1', mode: 'static', address: '10.0.96.126', prefix: 24, gateway: '10.0.96.1', dns: ['10.0.96.1'] });
      state = { ...state, phase: 'pending', deadline: Date.now() / 1000 + 120 };
      await route.fulfill({ json: { ...state, token: 't'.repeat(43) } });
    } else await route.fulfill({ json: state });
  });
  await page.route('https://10.0.96.126:10444/confirm', async route => {
    expect(route.request().method()).toBe('POST');
    expect(route.request().postDataJSON()).toEqual({ id: state.id, token: 't'.repeat(43) });
    expect(route.request().headers().cookie).toBeUndefined();
    expect(route.request().url()).not.toContain('t'.repeat(43));
    state.phase = 'confirmed';
    await route.fulfill({ json: { phase: 'confirmed' } });
  });
  await page.goto('/elderbrain/network');
  await expect(page.getByRole('combobox', { name: 'Network interface', exact: true })).toBeFocused();
  await page.getByRole('combobox', { name: 'Network interface', exact: true }).click();
  await page.getByRole('option', { name: 'eno1', exact: true }).click();
  await page.getByRole('combobox', { name: 'IPv4 mode', exact: true }).click();
  await page.getByRole('option', { name: 'Manual (static IPv4)', exact: true }).click();
  await page.getByLabel('IPv4 address', { exact: true }).fill('10.0.96.126');
  await page.getByLabel('Gateway', { exact: true }).fill('10.0.96.1');
  await page.getByLabel('IPv4 DNS servers', { exact: true }).fill('10.0.96.1');
  await page.getByRole('button', { name: 'Apply with timed rollback' }).click();
  await expect(page.getByRole('button', { name: 'Apply with timed rollback' })).toBeDisabled();
  await expect(page.getByLabel('New appliance IPv4')).toHaveValue('10.0.96.126');
  await expect(page.getByRole('button', { name: 'Confirm through new address' })).toBeFocused();
  await expect(page.getByRole('link', { name: 'Open setup at 10.0.96.126' })).toHaveCount(0);
  await page.getByRole('button', { name: 'Confirm through new address' }).click();
  await expect(page.getByText('Network configuration confirmed', { exact: true })).toBeVisible();
  const reconnect = page.getByRole('link', { name: 'Open setup at 10.0.96.126', exact: true });
  await expect(reconnect).toHaveAttribute('href', 'https://10.0.96.126/elderbrain/network');
  await expect(reconnect).toHaveAttribute('rel', 'noopener noreferrer');
  await expect(reconnect).toBeFocused();
});

test('reconnect link uses the confirmed destination, not an address edited during the request', async ({ page }) => {
  let state = { phase: 'idle', id: 'd'.repeat(32), deadline: 0 };
  let release!: () => void;
  const responseGate = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/api/network/change', async route => {
    if (route.request().method() === 'POST') {
      state = { ...state, phase: 'pending', deadline: Date.now() / 1000 + 120 };
      await route.fulfill({ json: { ...state, token: 't'.repeat(43) } });
    } else await route.fulfill({ json: state });
  });
  await page.route('https://10.0.96.126:10444/confirm', async route => {
    await responseGate;
    state.phase = 'confirmed';
    await route.fulfill({ json: { phase: 'confirmed' } });
  });
  await page.goto('/elderbrain/network');
  await page.getByRole('combobox', { name: 'Network interface', exact: true }).click();
  await page.getByRole('option', { name: 'eno1', exact: true }).click();
  await page.getByRole('button', { name: 'Apply with timed rollback' }).click();
  await page.getByLabel('New appliance IPv4').fill('10.0.96.126');
  const sent = page.waitForRequest('https://10.0.96.126:10444/confirm');
  await page.getByRole('button', { name: 'Confirm through new address' }).click();
  await sent;
  await page.getByLabel('New appliance IPv4').fill('10.0.96.127');
  await expect(page.getByRole('link', { name: /Open setup at/ })).toHaveCount(0);
  release();
  await expect(page.getByRole('link', { name: 'Open setup at 10.0.96.126', exact: true }))
    .toHaveAttribute('href', 'https://10.0.96.126/elderbrain/network');
  await expect(page.getByRole('link', { name: 'Open setup at 10.0.96.127', exact: true })).toHaveCount(0);
});

test('lost network response is not retried and cannot confirm without its token', async ({ page }) => {
  let requests = 0;
  let state = { phase: 'idle', id: 'b'.repeat(32), deadline: 0 };
  await page.route('**/api/network/change', async route => {
    if (route.request().method() === 'POST') {
      requests++;
      state = { ...state, phase: 'pending', deadline: Date.now() / 1000 + 120 };
      await route.abort();
    } else await route.fulfill({ json: state });
  });
  await page.goto('/elderbrain/network');
  await page.getByRole('combobox', { name: 'Network interface', exact: true }).click();
  await page.getByRole('option', { name: 'eno1', exact: true }).click();
  await page.getByRole('button', { name: 'Apply with timed rollback' }).click();
  await expect(page.getByText(/The result is unknown/)).toBeVisible();
  await expect(page.getByText('Network change: pending', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Confirm through new address' })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Apply with timed rollback' })).toBeDisabled();
  expect(requests).toBe(1);
});

test('network polling preserves typing and reload loses the confirmation token but permits rollback', async ({ page }) => {
  let state = { phase: 'idle', id: 'c'.repeat(32), deadline: 0 };
  await page.route('**/api/network/change', async route => {
    if (route.request().method() === 'POST') {
      state = { ...state, phase: 'pending', deadline: Date.now() / 1000 + 120 };
      await route.fulfill({ json: { ...state, token: 't'.repeat(43) } });
    } else await route.fulfill({ json: state });
  });
  await page.route('**/api/network/change/cancel', async route => {
    expect(route.request().postDataJSON()).toEqual({ id: state.id });
    state.phase = 'rolled-back';
    await route.fulfill({ json: state });
  });
  await page.goto('/elderbrain/network');
  await page.getByRole('combobox', { name: 'Network interface', exact: true }).click();
  await page.getByRole('option', { name: 'eno1', exact: true }).click();
  await page.getByRole('button', { name: 'Apply with timed rollback' }).click();
  const address = page.getByLabel('New appliance IPv4');
  await expect(address).toBeFocused();
  await address.fill('10.0.96.128');
  await page.waitForResponse(response => response.url().endsWith('/api/network/change') && response.request().method() === 'GET');
  await expect(address).toBeFocused();
  await expect(address).toHaveValue('10.0.96.128');
  await expect(page.getByRole('button', { name: 'Confirm through new address' })).toBeEnabled();
  await page.reload();
  await expect(page.getByText('Network change: pending', { exact: true })).toBeVisible();
  await address.fill('10.0.96.128');
  await expect(page.getByRole('button', { name: 'Confirm through new address' })).toBeDisabled();
  await page.getByRole('button', { name: 'Revert now', exact: true }).click();
  await expect(page.getByText('Original network configuration restored', { exact: true })).toBeVisible();
});

test("display preview survives reload, cancels without saving and blocks direct writes", async ({ page, request }) => {
  const before = await (await request.get('/elderbrain/api/config')).json();
  await page.goto('/elderbrain/displays');
  await page.getByLabel('LAN domain').fill('preview-only.example');
  await page.getByRole('button', { name: 'Preview display changes', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Keep display settings', exact: true })).toBeVisible();
  expect(await (await request.get('/elderbrain/api/config')).json()).toEqual(before);
  await page.reload();
  await expect(page.getByRole('button', { name: 'Keep display settings', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Keep display settings', exact: true })).toBeFocused();
  await expect(page.getByLabel('LAN domain')).toBeDisabled();
  const session = await (await request.get('/elderbrain/api/auth/session')).json();
  expect((await request.put('/elderbrain/api/config', { headers: { 'x-elderbrain-request': '1', 'x-csrf-token': session.csrf }, data: before })).status()).toBe(409);
  expect((await request.post('/elderbrain/api/display-preview/confirm', { headers: { 'x-elderbrain-request': '1' }, data: { id: 'd'.repeat(32) } })).status()).toBe(403);
  await page.getByRole('button', { name: 'Revert display settings', exact: true }).click();
  await expect(page.getByText('Display changes reverted', { exact: true })).toBeVisible();
  await expect(page.getByLabel('LAN domain')).toHaveValue(before.domain);
  expect(await (await request.get('/elderbrain/api/config')).json()).toEqual(before);
});

test("administration browser mode saves additional tabs and supports one screen", async ({ page }) => {
  await page.goto("/elderbrain/displays");
  const mode = page.getByRole("combobox", { name: "Browser mode 1", exact: true });
  await mode.click();
  await page.getByRole("option", { name: "Administration browser", exact: true }).click();
  await page.getByRole("button", { name: "Add tab", exact: true }).first().click();
  await page.getByLabel("Screen 1 additional tab 1", { exact: true }).fill("https://notes.example/");
  await page.getByRole("button", { name: "Remove second screen", exact: true }).click();
  await page.getByRole("button", { name: "Preview display changes", exact: true }).click();
  await page.getByRole("button", { name: "Keep display settings", exact: true }).click();
  await expect(page.getByText("Configuration saved", { exact: true })).toBeVisible();
  await page.reload();
  await expect(mode).toContainText("Administration browser");
  await expect(page.getByLabel("Screen 1 additional tab 1", { exact: true })).toHaveValue("https://notes.example/");
  await expect(page.getByRole("combobox", { name: "Output 2", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Add second screen", exact: true }).click();
  await page.getByRole("button", { name: "Preview display changes", exact: true }).click();
  await page.getByRole("button", { name: "Keep display settings", exact: true }).click();
  await expect(page.getByText("Configuration saved", { exact: true })).toBeVisible();
});

test("display dropdown discovers monitors and preserves a disconnected selection", async ({ page }) => {
  await page.goto("/elderbrain/displays");
  const output = page.getByRole("combobox", { name: "Output 1", exact: true });
  await expect(output).toBeEnabled();
  await output.click();
  await page.getByRole("option", { name: /DP-1 · Fixture Monitor · 1920×1080 · Active/ }).click();
  await expect(output).toContainText("DP-1");
  await page.route("**/elderbrain/api/displays", route => route.fulfill({ json: { at: Date.now() / 1000, outputs: [] } }));
  await expect(output).toContainText("Disconnected / not detected", { timeout: 10000 });
  await page.getByRole("button", { name: "Preview display changes" }).click();
  await page.getByRole("button", { name: "Keep display settings", exact: true }).click();
  await expect(page.getByText("Configuration saved", { exact: true })).toBeVisible();
  await page.reload();
  await expect(output).toContainText("DP-1");
  await expect(output).toContainText("Disconnected / not detected");
  await page.route("**/elderbrain/api/displays", route => route.fulfill({ status: 503, json: { error: "Unavailable" } }));
  await expect(output).toBeDisabled({ timeout: 10000 });
  await expect(output).toContainText("DP-1");
  await expect(page.getByText("Display discovery unavailable. Saved selections are preserved.")).toBeVisible();
});

test("keypads show host DHCP addresses separately from provisioning settings", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.goto("/elderbrain/keypads");
  await expect(page.getByText("10.0.96.125/24", { exact: true })).toBeVisible();
  await expect(page.getByText("DHCP", { exact: true })).toBeVisible();
  await expect(page.getByText("172.17.0.1/16", { exact: true })).toHaveCount(0);
  await expect(page.getByText(/Networking changes do not update keypads automatically/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Copy 10.0.96.125", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "Copy 10.0.96.125", exact: true }).click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe("10.0.96.125");
  await page.getByRole("link", { name: "Network", exact: true }).click();
  await expect(page.getByText("172.17.0.1/16", { exact: true })).toBeVisible();
  await expect(page.getByText("Internal container network", { exact: true })).toBeVisible();
  await page.route("**/elderbrain/api/network", route => route.fulfill({ status: 503, json: { error: "unavailable" } }));
  await page.reload();
  await expect(page.getByText(/Host network discovery unavailable/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Copy 10.0.96.125", exact: true })).toHaveCount(0);
});

test("overview renders host usage graphs and marks stale readings", async ({ page }) => {
  await page.goto("/elderbrain/");
  await expect(page.getByRole("img", { name: /CPU usage: 25.0%/ })).toBeVisible();
  await expect(page.getByText(/elderbrain-host · Uptime 1h 0m/)).toBeVisible();
  await expect(page.getByRole("img", { name: /RAM usage/ })).toBeVisible();
  await expect(page.getByRole("img", { name: /Storage: \// })).toBeVisible();
  await expect(page.locator("main pre")).toHaveCount(0);
  await page.screenshot({ path: "test-results/overview-metrics.png", fullPage: true });
  await page.route("**/elderbrain/api/status", route => route.fulfill({ json: {
    history: [{ at: Date.now() / 1000 - 120, cpu: 99, ram: null, disks: [] }], services: [], errors: [],
  } }));
  await page.reload();
  await expect(page.getByText("Host metrics are stale", { exact: true })).toBeVisible();
  await expect(page.getByRole("img", { name: /CPU usage: Unavailable/ })).toBeVisible();
});

test("navigation protects unsaved edits and works on mobile", async ({ page }) => {
  await page.goto("/elderbrain/displays");
  await expect(page.getByLabel("LAN domain")).not.toHaveValue("");
  await page.getByLabel("LAN domain").fill("unsaved.example");
  page.once("dialog", dialog => dialog.dismiss());
  await page.getByRole("link", { name: "Foundry", exact: true }).click();
  await expect(page).toHaveURL(/\/displays$/);
  await expect(page.getByLabel("LAN domain")).toHaveValue("unsaved.example");
  page.once("dialog", dialog => dialog.accept());
  await page.getByRole("link", { name: "Foundry", exact: true }).click();
  await expect(page.getByLabel("Account email")).toBeVisible();
  await expect(page.getByLabel("Account email")).toBeFocused();
  await expect(page.getByLabel("LAN domain")).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Menu", exact: true }).click();
  await page.getByRole("link", { name: "Network", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Network", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Menu", exact: true })).toHaveAttribute("aria-expanded", "false");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("account uses private SMTP defaults and allows an optional custom server", async ({ page }) => {
  await page.goto("/elderbrain/account");
  await expect(page.getByText("Using the email server configured for this appliance.")).toBeVisible();
  await expect(page.getByLabel("SMTP server", { exact: true })).toHaveCount(0);
  await expect(page.locator("body")).not.toContainText("default-private-canary");
  await page.getByRole("checkbox", { name: "Use a custom email server" }).check();
  await expect(page.getByLabel("SMTP server", { exact: true })).toBeVisible();
  await expect(page.getByLabel("SMTP password", { exact: true })).toHaveValue("");
  await page.getByRole("checkbox", { name: "Use a custom email server" }).uncheck();
  await expect(page.getByLabel("SMTP server", { exact: true })).toHaveCount(0);
});

test("interrupted flashing exposes actionable recovery without offering automatic resume", async ({ page }) => {
  const id = "c".repeat(32);
  await page.route("**/elderbrain/api/jobs", route => route.fulfill({ json: [{
    id, kind: "keypad-install", state: "interrupted", stage: "flash-firmware",
    error: "Installation worker stopped.",
  }] }));
  await page.goto("/elderbrain/keypads");
  await expect(page.getByRole("heading", { name: "Recovery steps" })).toBeVisible();
  await expect(page.getByText("Full installation ID: " + id)).toBeVisible();
  await expect(page.getByText(/Firmware may be incomplete/)).toBeVisible();
  await expect(page.getByText(/Do not copy sectors from another keypad/)).toBeVisible();
  await expect(page.getByText(/No automatic resume is performed/)).toBeVisible();
});

test("inventory distinguishes confirmed, overridden and unknown LED state", async ({ page }) => {
  let appliedLeds: { led1: string; led2: string } | null = { led1: "#ff0000", led2: "#0000ff" };
  await page.route("**/elderbrain/api/keypads", route => route.fulfill({ json: [{
    id: "led-keypad", name: "", seat: "", connection: "connected", hardware: "mindflayer-keypad-v1",
    firmware: "1.2.3", lastSeen: null, provisioning: "provisioned", registration: "registered",
    desiredRevision: 2, appliedRevision: appliedLeds?.led1 === "#ff0000" ? 2 : null,
    ledPreferences: { led1: "#ff0000", led2: "#0000ff" }, appliedLeds,
  }] }));
  await page.goto("/elderbrain/keypads");
  await expect(page.getByText(/Firmware-confirmed LEDs: #ff0000 \/ #0000ff/)).toContainText("Matches saved preferences");
  appliedLeds = { led1: "#ffffff", led2: "#0000ff" };
  await page.reload();
  await expect(page.getByText(/Firmware-confirmed LEDs: #ffffff \/ #0000ff/)).toContainText("Differs from saved preferences");
  appliedLeds = null;
  await page.reload();
  await expect(page.getByText(/LED application not confirmed/)).toBeVisible();
  await expect(page.getByText(/Firmware-confirmed LEDs:/)).toHaveCount(0);
});

test("Nuxt UI works through the appliance prefix and preserves unsaved edits", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto("/elderbrain/displays");
  await expect(page.getByRole("heading", { name: "Displays", exact: true })).toBeVisible();
  await expect(page.getByLabel("LAN domain")).toHaveValue("elderbrain.local");
  await page.getByLabel("LAN domain").fill("table.example");
  await page.waitForTimeout(5500);
  await expect(page.getByLabel("LAN domain")).toHaveValue("table.example");
  await page.getByRole("button", { name: "Preview display changes" }).click();
  await page.getByRole("button", { name: "Keep display settings", exact: true }).click();
  await expect(page.getByText("Configuration saved", { exact: true })).toBeVisible();
  expect(new URL(page.url()).pathname).toBe("/elderbrain/displays");
  await page.reload();
  await expect(page.getByLabel("LAN domain")).toHaveValue("table.example");
  await page.getByRole("link", { name: "Keypads", exact: true }).click();
  await page.getByRole("button", { name: "Identify", exact: true }).click();
  await expect(page.getByText("Identification colors sent", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Overview", exact: true }).click();
  await page.getByRole("button", { name: "Restart Mindflayer" }).click();
  await expect(page.getByText("Restart requested", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Foundry", exact: true }).click();
  await page.getByLabel("Account email").fill("test@example.com");
  await page.getByLabel("Password", { exact: true }).fill("test-secret");
  await page.getByRole("button", { name: "Save credentials", exact: true }).click();
  await expect(page.getByText("Credentials stored and Foundry started", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Password", { exact: true })).toHaveValue("");
  await page.getByRole("button", { name: "Remove stored credentials" }).click();
  await expect(page.getByText("Credentials removed", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Logs", exact: true }).click();
  await expect(page.getByLabel("Foundry log output")).toContainText("Foundry test log");
  await page.getByLabel("Search logs").fill("no matching line");
  await expect(page.getByLabel("Foundry log output")).not.toContainText("Foundry test log");
  await page.getByLabel("Search logs").fill("");
  await page.getByRole("button", { name: "Pause logs" }).click();
  await expect(page.getByRole("button", { name: "Resume logs" })).toBeVisible();
  await page.getByRole("button", { name: "Resume logs" }).click();
  await page.getByRole("link", { name: "Keypads", exact: true }).click();
  await page.getByLabel("Wi-Fi SSID").fill("Table Network");
  await page.getByLabel("Wi-Fi password", { exact: true }).fill("private-network-password");
  await page.getByLabel("Appliance address reachable by keypads").fill("192.168.1.42");
  await page.getByRole("button", { name: "Save desired settings" }).click();
  await expect(page.getByText("Desired keypad settings saved", { exact: true })).toBeVisible();
  await page.getByLabel("Name for test-keypad").fill("Alice");
  await page.getByRole("checkbox", { name: "Set LED colours for test-keypad", exact: true }).check();
  await page.getByLabel("LED 1 for test-keypad", { exact: true }).fill("#ff8000");
  await page.getByLabel("LED 2 for test-keypad", { exact: true }).fill("#0080ff");
  await page.locator("form").filter({ has: page.getByLabel("Name for test-keypad") }).getByRole("button", { name: "Save keypad preferences" }).click();
  await expect(page.getByText("Keypad preferences saved", { exact: true })).toBeVisible();
  await expect(page.getByText("LED command sent; waiting for firmware acknowledgement. Older firmware cannot confirm application.", { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("LED 1 for test-keypad", { exact: true })).toHaveValue("#ff8000");
  await expect(page.getByLabel("LED 2 for test-keypad", { exact: true })).toHaveValue("#0080ff");
  expect(errors).toEqual([]);
  await page.screenshot({ path: "test-results/setup-desktop.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: "test-results/setup-mobile.png", fullPage: true });
});

test("production API preserves health, metadata, errors and method boundaries", async ({ request }) => {
  const session = await (await request.get("/elderbrain/api/auth/session")).json();
  const headers = { "x-elderbrain-request": "1", "x-csrf-token": session.csrf };
  expect(await (await request.get("/elderbrain/health")).json()).toEqual({ ok: true });
  const status = await request.get("/elderbrain/api/status");
  expect(status.headers()["cache-control"]).toBe("no-store");
  expect((await status.json()).mindflayerServerImage).toBe("test-registry-image");
  expect((await request.put("/elderbrain/api/config", { headers, data: { domain: "bad" } })).status()).toBe(409);
  expect((await request.get("/elderbrain/api/foundry/credentials")).status()).toBe(404);
  expect((await request.post("/elderbrain/api/actions/shutdown", { headers })).status()).toBe(404);
  const install = { usbId: "4".repeat(32), version: "1.2.3", revision: 1, adopt: false, confirm: true };
  expect((await request.post("/elderbrain/api/keypads/install", { data: install })).status()).toBe(403);
  expect((await request.post("/elderbrain/api/keypads/install", { headers, data: { ...install, confirm: false } })).status()).toBe(400);
  expect((await request.post("/elderbrain/api/keypads/install", { headers, data: { ...install, usbId: "/dev/ttyUSB0" } })).status()).toBe(400);
  expect((await request.post("/elderbrain/api/keypads/install", { headers, data: { ...install, adopt: "true" } })).status()).toBe(400);
  expect((await request.put("/elderbrain/api/config", { headers, data: "x".repeat(70000) })).status()).toBe(409);
  expect((await request.get("/elderbrain/api/status")).status()).toBe(200);
});

test("direct hostname entry also hydrates", async ({ page }) => {
  await page.goto("http://127.0.0.1:18080/");
  await expect(page.getByRole("heading", { name: "Overview", exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Displays", exact: true }).click();
  await expect(page.getByLabel("LAN domain")).toBeVisible();
});

test("backup panel requires downtime consent and offers an authenticated download", async ({ page, request }) => {
  await page.goto("/elderbrain/backups");
  const create = page.getByRole("button", { name: "Create configuration backup" });
  await expect(create).toBeDisabled();
  await page.getByRole("checkbox", { name: "I understand the temporary downtime and unencrypted download" }).check();
  await create.click();
  const download = page.getByRole("link", { name: "Download .tar.zst" }).first();
  await expect(download).toBeVisible();
  const response = await request.get((await download.getAttribute("href"))!);
  expect(response.status()).toBe(200);
  expect(response.headers()["content-disposition"]).toContain("attachment");
  expect(response.headers()["cache-control"]).toBe("no-store");
  expect(await response.text()).toBe("test-archive");
  await page.reload();
  await expect(page.getByRole("link", { name: "Download .tar.zst" }).first()).toBeVisible();
});

test("restore upload shows preview before explicit replacement confirmation", async ({ page }) => {
  await page.goto("/elderbrain/backups");
  await page.locator('input[type="file"]').setInputFiles({ name: "backup.tar.zst", mimeType: "application/octet-stream", buffer: Buffer.from("test-upload") });
  await page.getByRole("button", { name: "Upload and validate backup" }).click();
  await expect(page.getByText("Appliance: fixture-appliance", { exact: false })).toBeVisible();
  const restore = page.getByRole("button", { name: "Restore this backup" }).first();
  await expect(restore).toBeDisabled();
  await page.getByRole("checkbox", { name: "I trust this archive and confirm replacing configuration, accounts, keys and SSH access" }).first().check();
  const submission = page.waitForResponse(response => response.url().endsWith("/restore") && response.request().method() === "POST");
  await restore.click();
  expect((await submission).status()).toBe(202);
});

test("remote backup settings save and archive selection produces a restore preview", async ({ page, request }) => {
  await page.goto("/elderbrain/backups");
  await page.getByLabel("Backup server hostname").fill("nas.example.com");
  await page.getByLabel("NFS export path").fill("/exports/backups");
  await page.getByLabel("Repository passphrase (blank: keep existing or generate)").fill("test-repository-passphrase");
  await page.getByRole("button", { name: "Save remote backup settings" }).click();
  await expect(page.getByText("Remote backup settings saved", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Repository passphrase (blank: keep existing or generate)")).toHaveValue("");
  expect(await (await request.get("/elderbrain/api/borg/settings")).text()).not.toContain("test-repository-passphrase");
  await expect(page.getByRole("button", { name: "Initialize repository" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Back up remotely now" })).toBeDisabled();
  await page.getByRole("button", { name: "List remote archives" }).click();
  await page.getByRole("button", { name: "Retrieve restore preview" }).first().click();
  await expect(page.getByText("Appliance: remote-fixture", { exact: false })).toBeVisible();
  const recovery = page.getByRole("button", { name: "Create repository recovery kit" });
  await expect(recovery).toBeDisabled();
  await page.getByRole("checkbox", { name: "I understand the recovery kit contains repository passwords and private keys" }).check();
  await recovery.click();
  const link = page.getByRole("link", { name: "Download recovery kit" });
  await expect(link).toBeVisible();
  const download = await request.get((await link.getAttribute("href"))!);
  expect(download.headers()["content-disposition"]).toContain("attachment");
  expect(download.headers()["cache-control"]).toBe("no-store");
  expect((await download.json()).settings.passphrase).toBe("fixture-kit-secret");
  expect(await (await request.get("/elderbrain/api/jobs")).text()).not.toContain("fixture-kit-secret");
});

test("encrypted export requires matching passwords and does not return them in jobs", async ({ page, request }) => {
  await page.goto("/elderbrain/backups");
  await page.getByRole("checkbox", { name: "Password-encrypt the manual export" }).check();
  await page.getByLabel("Export encryption passphrase", { exact: true }).fill("test-encrypted-export-password");
  await page.getByRole("checkbox", { name: "I understand the temporary downtime and will keep the export passphrase safe" }).check();
  const create = page.getByRole("button", { name: "Create configuration backup" });
  await expect(create).toBeDisabled();
  await page.getByLabel("Confirm export passphrase").fill("test-encrypted-export-password");
  await create.click();
  await expect(page.getByLabel("Export encryption passphrase", { exact: true })).toHaveValue("");
  const link = page.getByRole("link", { name: "Download encrypted backup" });
  await expect(link).toBeVisible();
  const download = await request.get((await link.getAttribute("href"))!);
  expect(download.headers()["content-disposition"]).toContain(".tar.zst.gpg");
  expect(await (await request.get("/elderbrain/api/jobs")).text()).not.toContain("test-encrypted-export-password");
});

test("registered keypads are visible before their first connection", async ({ page, request }) => {
  await page.goto("/elderbrain/keypads");
  const record = page.locator("div.border.rounded").filter({ has: page.getByText("offline-keypad", { exact: true }) });
  await expect(record.getByText("Server registration: registered")).toBeVisible();
  await expect(record.getByText(/Last seen: Never/)).toBeVisible();
  const response = await request.get("/elderbrain/api/keypads");
  expect(response.headers()["x-elderbrain-inventory-source"]).toBe("current");
  expect((await response.json()).find((r: { id: string }) => r.id === "offline-keypad").appliedRevision).toBeNull();
});

test("USB installation submits explicit target and saved revision and displays verified job", async ({ page }) => {
  await page.goto("/elderbrain/keypads");
  await expect(page.getByText("Fixture USB adapter", { exact: true })).toBeVisible();
  await expect(page.getByText(/Chip and flash size not yet verified/)).toBeVisible();
  await page.getByRole("button", { name: "Scan appliance USB ports" }).click();
  await expect(page.getByText(/Selected stable firmware: 1.2.3/)).toBeVisible();
  await expect(page.getByRole("checkbox", { name: "Allow adoption of a keypad from another installation" })).not.toBeChecked();
  await page.getByLabel("Wi-Fi SSID").fill("Installation Network");
  await page.getByLabel("Wi-Fi password", { exact: true }).fill("installation-test-password");
  await page.getByLabel("Appliance address reachable by keypads").fill("192.168.1.42");
  await page.getByRole("button", { name: "Save desired settings" }).click();
  await expect(page.getByText(/Saved settings revision .*Installation Network/)).toBeVisible();
  const request = page.waitForRequest(request => request.url().endsWith("/api/keypads/install") && request.method() === "POST");
  await page.getByRole("button", { name: "Install & provision Fixture USB adapter" }).click();
  const submitted = (await request).postDataJSON();
  expect(submitted).toMatchObject({ usbId: "4".repeat(32), version: "1.2.3", adopt: false, confirm: true });
  expect(submitted.revision).toBeGreaterThan(0);
  expect(JSON.stringify(submitted)).not.toContain("installation-test-password");
  await expect(page.getByText(/Authenticated keypad installed-fixture/)).toBeVisible();
  await expect(page.getByText("installed-fixture", { exact: true })).toBeVisible();
  const inventory = page.locator("div.border").filter({ has: page.getByText("installed-fixture", { exact: true }) }).last();
  await expect(inventory).toContainText(`Applied revision ${submitted.revision}`);
  await expect(inventory).toContainText("Firmware: 1.2.3");
});

test("installation stays disabled without a trusted release", async ({ page }) => {
  await page.route("**/api/keypads/release", route => route.fulfill({ status: 400, contentType: "application/json", body: JSON.stringify({ error: "No trusted serial-install release available" }) }));
  await page.goto("/elderbrain/keypads");
  await expect(page.getByText("No trusted serial-install release available", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Install & provision Fixture USB adapter" })).toBeDisabled();
});

test("encrypted upload clears its password and still requires restore confirmation", async ({ page, request }) => {
  await page.goto("/elderbrain/backups");
  await page.locator('input[type="file"]').setInputFiles({ name: "backup.tar.zst.gpg", mimeType: "application/octet-stream", buffer: Buffer.from("encrypted-fixture") });
  await expect(page.getByRole("checkbox", { name: "This backup is password-encrypted" })).toBeChecked();
  const upload = page.getByRole("button", { name: "Upload and validate backup" });
  await expect(upload).toBeDisabled();
  await page.getByLabel("Restore decryption passphrase").fill("test-upload-decryption-password");
  await upload.click();
  await expect(page.getByLabel("Restore decryption passphrase")).toHaveValue("");
  const preview = page.locator("div.border-t").filter({ hasText: "Appliance: encrypted-fixture" });
  await expect(preview.getByRole("button", { name: "Restore this backup" })).toBeDisabled();
  await preview.getByRole("checkbox").check();
  const response = page.waitForResponse(r => r.url().endsWith("/restore") && r.request().method() === "POST");
  await preview.getByRole("button", { name: "Restore this backup" }).click();
  expect((await response).status()).toBe(202);
  expect(await (await request.get("/elderbrain/api/jobs")).text()).not.toContain("test-upload-decryption-password");
});
