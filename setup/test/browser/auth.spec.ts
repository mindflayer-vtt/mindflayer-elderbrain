import { test, expect } from "@playwright/test";

test("all administration deep links remain behind login", async ({ page }) => {
  for (const section of ["displays", "foundry", "keypads", "network", "backups", "logs", "account"]) {
    await page.goto("/elderbrain/" + section);
    await expect(page.getByRole("heading", { name: "Sign in to Elderbrain" })).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Administration" })).toHaveCount(0);
  }
});

test("local login keyboard selector searches and applies layouts without exposing its capability in the URL", async ({ page, request }) => {
  for (const prefix of ["http://127.0.0.1:18080/api/", "/elderbrain/api/"]) {
    expect((await request.get(prefix + "keyboard", { headers: { "x-kiosk-keyboard": "b".repeat(64) } })).status()).toBe(403);
  }
  await page.goto("/elderbrain/#kiosk-keyboard=" + "a".repeat(64));
  await expect(page.getByText("Active: English (US)", { exact: true })).toBeVisible();
  await expect(page).toHaveURL(/\/elderbrain\/$/);
  await page.getByRole("button", { name: "Keyboard layout", exact: true }).click();
  await page.getByPlaceholder("Search keyboard layouts…").fill("German");
  await expect(page.getByRole("option", { name: "English (US)", exact: true })).toHaveCount(0);
  await page.getByRole("option", { name: "German", exact: true }).click();
  await expect(page.getByText("Active: German", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Sign in to Elderbrain" })).toBeVisible();
});

test("unauthenticated callers cannot read or change administration through either route", async ({ request, page }) => {
  for (const prefix of ["http://127.0.0.1:18080/api/", "/elderbrain/api/"]) {
    expect((await request.get(prefix + "keyboard")).status()).toBe(403);
    expect((await request.post(prefix + "keyboard", { headers: { "x-elderbrain-request": "1" }, data: { layout: "de:" } })).status()).toBe(403);
    expect((await request.get(prefix + "config")).status()).toBe(401);
    expect((await request.get(prefix + "status")).status()).toBe(401);
    expect((await request.get(prefix + "foundry/beamer")).status()).toBe(401);
    expect((await request.put(prefix + "foundry/beamer", { headers: { "x-elderbrain-request": "1" }, data: {} })).status()).toBe(401);
    expect((await request.delete(prefix + "foundry/beamer", { headers: { "x-elderbrain-request": "1" } })).status()).toBe(401);
    expect((await request.get(prefix + "network")).status()).toBe(401);
    expect((await request.get(prefix + "network/change")).status()).toBe(401);
    expect((await request.post(prefix + "network/change", { headers: { "x-elderbrain-request": "1" }, data: { interface: "ens3", mode: "dhcp" } })).status()).toBe(401);
    expect((await request.post(prefix + "network/change/cancel", { headers: { "x-elderbrain-request": "1" }, data: { id: "a".repeat(32) } })).status()).toBe(401);
    expect((await request.get(prefix + "displays")).status()).toBe(401);
    expect((await request.get(prefix + "display-preview")).status()).toBe(401);
    expect((await request.post(prefix + "display-preview", { headers: { "x-elderbrain-request": "1" }, data: {} })).status()).toBe(401);
    expect((await request.post(prefix + "display-preview/confirm", { headers: { "x-elderbrain-request": "1" }, data: { id: "d".repeat(32) } })).status()).toBe(401);
    expect((await request.get(prefix + "controllers")).status()).toBe(401);
    expect((await request.get(prefix + "logs/foundry")).status()).toBe(401);
    expect((await request.get(prefix + "logs/foundry/download")).status()).toBe(401);
    expect((await request.get(prefix + "keypad-settings")).status()).toBe(401);
    expect((await request.get(prefix + "keypads/usb")).status()).toBe(401);
    expect((await request.get(prefix + "keypads/release")).status()).toBe(401);
    expect((await request.post(prefix + "keypads/install", { headers: { "x-elderbrain-request": "1" }, data: { confirm: true } })).status()).toBe(401);
    expect((await request.get(prefix + "jobs")).status()).toBe(401);
    expect((await request.get(prefix + "borg/settings")).status()).toBe(401);
    expect((await request.get(prefix + "borg/recovery-kits/" + "f".repeat(32) + "/download")).status()).toBe(401);
    expect((await request.put(prefix + "borg/settings", { headers: { "x-elderbrain-request": "1" }, data: {} })).status()).toBe(401);
    expect((await request.post(prefix + "borg/init", { headers: { "x-elderbrain-request": "1" }, data: { confirm: true } })).status()).toBe(401);
    expect((await request.get(prefix + "backups/" + "a".repeat(32) + "/download")).status()).toBe(401);
    expect((await request.post(prefix + "backups", { headers: { "x-elderbrain-request": "1" } })).status()).toBe(401);
    expect((await request.post(prefix + "backups/upload", { headers: { "x-elderbrain-request": "1" }, data: "archive" })).status()).toBe(401);
    expect((await request.post(prefix + "backups/upload-encrypted", { headers: { "x-elderbrain-request": "1" }, data: "archive" })).status()).toBe(401);
    expect((await request.post(prefix + "backups/preview-encrypted", { headers: { "x-elderbrain-request": "1" }, data: {} })).status()).toBe(401);
    expect((await request.post(prefix + "backups/" + "b".repeat(32) + "/restore", { headers: { "x-elderbrain-request": "1" }, data: { confirm: true } })).status()).toBe(401);
    expect((await request.post(prefix + "actions/restart-foundry", { headers: { "x-elderbrain-request": "1" } })).status()).toBe(401);
    expect((await request.delete(prefix + "foundry/credentials", { headers: { "x-elderbrain-request": "1" } })).status()).toBe(401);
  }
  await page.goto("/elderbrain/");
  await expect(page.getByRole("heading", { name: "Sign in to Elderbrain" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Restart Foundry" })).toHaveCount(0);
  await expect(page.getByLabel("Administrator password", { exact: true })).toBeFocused();
  await page.getByLabel("Administrator password", { exact: true }).fill("browser-test-password");
  await expect(page.getByLabel("Administrator password", { exact: true })).toHaveAttribute("type", "password");
  await page.getByRole("button", { name: "Show password", exact: true }).click();
  await expect(page.getByLabel("Administrator password", { exact: true })).toHaveAttribute("type", "text");
  await expect(page.getByLabel("Administrator password", { exact: true })).toHaveValue("browser-test-password");
  await page.getByRole("button", { name: "Hide password", exact: true }).click();
  await expect(page.getByLabel("Administrator password", { exact: true })).toHaveAttribute("type", "password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("button", { name: "Restart Foundry" })).toBeVisible();
  await page.getByRole("link", { name: "Foundry", exact: true }).click();
  const foundryPassword = page.getByLabel("Password", { exact: true });
  await foundryPassword.fill("test-foundry-secret");
  const foundryForm = page.locator("form").filter({ has: foundryPassword });
  await foundryForm.getByRole("button", { name: "Show password", exact: true }).click();
  await expect(foundryPassword).toHaveAttribute("type", "text");
  await foundryPassword.fill("");
  await expect(foundryPassword).toHaveAttribute("type", "password");
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Sign in to Elderbrain" })).toBeVisible();
});

test("CSRF, origin checking and logout revocation protect authenticated requests", async ({ request }) => {
  const login = await request.post("/elderbrain/api/auth/login", {
    headers: { "x-elderbrain-request": "1" }, data: { username: "admin", password: "browser-test-password" },
  });
  expect(login.ok()).toBe(true);
  expect(login.headers()["set-cookie"]).toContain("HttpOnly");
  expect(login.headers()["set-cookie"]).toContain("SameSite=Strict");
  const download = await request.get("/elderbrain/api/logs/foundry/download");
  expect(download.headers()["content-disposition"]).toContain("attachment");
  expect(await download.text()).toContain("Foundry test log");
  const session = await login.json();
  expect((await request.put('/elderbrain/api/foundry/beamer', {
    headers: { 'x-elderbrain-request': '1', 'x-csrf-token': 'bad' }, data: {},
  })).status()).toBe(403);
  expect((await request.delete('/elderbrain/api/foundry/beamer', {
    headers: { 'x-elderbrain-request': '1', 'x-csrf-token': session.csrf, origin: 'https://attacker.invalid' },
  })).status()).toBe(403);
  for (const action of ["network/change", "network/change/cancel"]) {
    expect((await request.post("/elderbrain/api/" + action, {
      headers: { "x-elderbrain-request": "1", "x-csrf-token": "bad" }, data: {},
    })).status()).toBe(403);
    expect((await request.post("/elderbrain/api/" + action, {
      headers: { "x-elderbrain-request": "1", "x-csrf-token": session.csrf, origin: "https://attacker.invalid" }, data: {},
    })).status()).toBe(403);
  }
  expect((await request.post("/elderbrain/api/actions/restart-foundry")).status()).toBe(403);
  expect((await request.post("/elderbrain/api/actions/restart-foundry", {
    headers: { "x-elderbrain-request": "1", "x-csrf-token": "bad" },
  })).status()).toBe(403);
  expect((await request.post("/elderbrain/api/actions/restart-foundry", {
    headers: { "x-elderbrain-request": "1", "x-csrf-token": session.csrf, origin: "https://attacker.invalid" },
  })).status()).toBe(403);
  const headers = { "x-elderbrain-request": "1", "x-csrf-token": session.csrf };
  expect((await request.post("/elderbrain/api/auth/logout", { headers, data: {} })).ok()).toBe(true);
  expect((await request.get("/elderbrain/api/config")).status()).toBe(401);
});
