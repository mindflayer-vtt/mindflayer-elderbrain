// Opt-in probe against the isolated fixture, never a production world.
import fs from 'node:fs';
import { parseEnv } from 'node:util';
import { randomBytes } from 'node:crypto';
import { chromium } from '../../setup/node_modules/@playwright/test/index.mjs';
import { loginBeamer } from '../../provisioning/graphics/beamer-login.mjs';
import { runBeamer } from '../../provisioning/graphics/beamer-worker.mjs';
import os from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';

const env = parseEnv(fs.readFileSync(new URL('../../../foundryvtt-mindflayer/.env', import.meta.url), 'utf8'));
const base = 'http://127.0.0.1:30001';
const world = 'elderbrain-beamer';
const password = randomBytes(24).toString('base64url');
const name = 'Beamer probe ' + randomBytes(4).toString('hex');
const browser = await chromium.launch({ headless: true });
let gm, identifier;
let stage = 'GM login';
try {
  async function join(page, username, secret) {
    page.on('request', request => {
      if (request.url().includes(secret)) throw new Error('Credential appeared in request URL');
    });
    await page.goto(`${base}/join?world=${world}`);
    const selector = page.locator('select[name="userid"], select[name="user"]');
    if (await selector.count()) await selector.selectOption({ label: username }, { force: true });
    else await page.locator('input[name="username"]').fill(username);
    await page.locator('input[name="password"]').fill(secret);
    await page.locator('button[name="join"]').click();
    await page.waitForFunction(() => globalThis.game?.ready === true, null, { timeout: 60000 });
    if (await page.evaluate(() => game.world.id) !== world) throw new Error('Unexpected world');
  }
  gm = await browser.newPage();
  await join(gm, 'Gamemaster', env.FOUNDRY_TEST_PASSWORD);
  stage = 'module creation';
  console.log('Fixture preflight:', JSON.stringify(await gm.evaluate(() => {
    const module = game.modules.get('mindflayer-token-controller')?.instance?.modules.BeamerUsers;
    return { core: game.version, expectedWorld: game.world.id === 'elderbrain-beamer', isGM: game.user.isGM,
      modulePresent: Boolean(module), loaded: Boolean(module?.loaded), selected: Boolean(module?.selectedId),
      modules: Object.keys(game.modules.get('mindflayer-token-controller')?.instance?.modules ?? {}) };
  })));
  await gm.evaluate(() => {
    if (game.world.id !== 'elderbrain-beamer' || !game.user.isGM || game.version !== '14.367') throw new Error('Wrong test runtime');
    const module = game.modules.get('mindflayer-token-controller')?.instance?.modules.BeamerUsers;
    if (!module?.loaded || module.selectedId) throw new Error('Fixture is not available for Beamer creation');
    const menu = game.settings.menus.get('mindflayer-token-controller.beamerUser');
    if (!menu?.restricted) throw new Error('GM restriction missing');
    new menu.type().render(true);
  });
  const panel = gm.locator('#mindflayer-beamer-user-config');
  await panel.locator('[name="name"]').fill(name);
  await panel.locator('[name="password"]').fill(password);
  await panel.getByRole('button', { name: 'Show password' }).click();
  if (await panel.locator('[name="password"]').getAttribute('type') !== 'text') throw new Error('Reveal failed');
  await panel.getByRole('button', { name: 'Hide password' }).click();
  await panel.getByRole('button', { name: 'Configure Beamer user' }).click();
  await gm.waitForFunction(() => Boolean(game.modules.get('mindflayer-token-controller').instance.modules.BeamerUsers.selectedId));
  identifier = await gm.evaluate(() => game.modules.get('mindflayer-token-controller').instance.modules.BeamerUsers.selectedId);
  await panel.locator('#beamer-world-id').waitFor();
  if (await panel.locator('#beamer-world-id').inputValue() !== world || await panel.locator('#beamer-user-id').inputValue() !== identifier) throw new Error('Pairing identifiers missing from GM form');
  await panel.locator('#beamer-user-id').click();
  if (!await panel.locator('#beamer-user-id').evaluate(field => field.selectionStart === 0 && field.selectionEnd === field.value.length)) throw new Error('Pairing ID selection failed');
  stage = 'explicit adoption';
  await gm.evaluate(async id => {
    const namespace = 'mindflayer-token-controller';
    const module = game.modules.get(namespace).instance.modules.BeamerUsers;
    const before = JSON.stringify(game.users.get(id).toObject());
    // Reset only the test-owned selection to exercise explicit adoption.
    if (module.selectedId !== id) throw new Error('Unexpected selection');
    await game.settings.set(namespace, 'beamerUserId', '');
    let rejected = false;
    try { await module.adopt({ userId: id }); } catch { rejected = true; }
    if (!rejected || module.selectedId) throw new Error('Implicit adoption was accepted');
    const result = await module.adopt({ userId: id, confirm: true });
    if (result.state !== 'configured' || module.selectedId !== id) throw new Error('Adoption failed');
    if (JSON.stringify(game.users.get(id).toObject()) !== before) throw new Error('Adoption changed the user');
  }, identifier);
  console.log('PASS: module-managed creation and explicit adoption preserve the user document.');
  stage = 'adoption form';
  await gm.evaluate(async id => {
    const namespace = 'mindflayer-token-controller';
    if (game.settings.get(namespace, 'beamerUserId') !== id) throw new Error('Unexpected selection');
    await game.settings.set(namespace, 'beamerUserId', '');
    for (const app of Object.values(ui.windows)) {
      if (app.id === 'mindflayer-beamer-user-config') await app.close();
    }
    new (game.settings.menus.get(`${namespace}.beamerUser`).type)().render(true);
  }, identifier);
  await panel.locator('[name="mode"]').selectOption('adopt');
  await panel.locator('[name="userId"]').selectOption(identifier);
  await panel.locator('[name="confirm"]').check();
  await panel.getByRole('button', { name: 'Configure Beamer user' }).click();
  await gm.waitForFunction(id => game.modules.get('mindflayer-token-controller').instance.modules.BeamerUsers.selectedId === id, identifier);
  console.log('PASS: GM creation/reveal and explicit adoption forms.');
  stage = 'login safety guards';
  const gmId = await gm.evaluate(() => game.user.id);
  for (const [worldId, userId, expected] of [["not-the-running-world", identifier, "world-not-running"], [world, gmId, "review-required"]]) {
    const context = await browser.newContext();
    try {
      const page = await context.newPage();
      let submitted = false;
      page.on('request', request => { if (request.method() === 'POST') submitted = true; });
      const result = await loginBeamer(page, { origin: base, worldId, userId, password });
      if (result.state !== expected || submitted || page.url() !== 'about:blank') throw new Error('Unsafe login preflight');
    } finally { await context.close(); }
  }
  console.log('PASS: wrong world and GM account rejected before password submission.');
  const displayContext = await browser.newContext();
  const display = await displayContext.newPage();
  stage = 'Player login';
  const username = await gm.evaluate(id => game.users.get(id).name, identifier);
  const login = await loginBeamer(display, { origin: base, worldId: world, username, password });
  if (login.state !== 'ready') throw new Error('Beamer verification failed');
  console.log('PASS: reusable Beamer login verifier reports ready.');
  const result = await display.evaluate(() => ({
    core: game.version, world: game.world.id, role: game.user.role, isGM: game.user.isGM,
    canCreateUsers: foundry.documents.User.canUserCreate(game.user),
    enabledPermissions: Object.keys(CONST.USER_PERMISSIONS).filter(key => game.user.can(key)),
    canvasReady: game.canvas.initialized,
    moduleActive: game.modules.get('mindflayer-token-controller')?.active,
    moduleLoaded: Boolean(game.modules.get('mindflayer-token-controller')?.instance),
    cameraLoaded: Boolean(game.modules.get('mindflayer-token-controller')?.instance?.modules.CameraControl?.loaded),
    cameraMode: game.modules.get('mindflayer-token-controller')?.instance?.settings.camera.control,
  }));
  if (result.isGM || result.canCreateUsers || result.enabledPermissions.length || !result.canvasReady) throw new Error('Unexpected player privileges or unavailable canvas');
  if (!result.cameraLoaded || result.cameraMode !== 'focusPlayers') {
    console.log('Camera verification:', JSON.stringify({ loaded: result.cameraLoaded, mode: result.cameraMode }));
    throw new Error('Beamer camera default is not active');
  }
  console.log('PASS: real isolated Player login:', JSON.stringify(result));
  for (const mode of ['off', 'default']) {
    const previous = await display.evaluateHandle(() => game.modules.get('mindflayer-token-controller').instance.modules.CameraControl);
    await display.evaluate(mode => game.settings.set('mindflayer-token-controller', 'cameraControl', mode), mode);
    await display.waitForFunction(previous => {
      const camera = game.modules.get('mindflayer-token-controller').instance.modules.CameraControl;
      return camera !== previous && camera?.loaded;
    }, previous);
    const effective = await display.evaluate(() => game.modules.get('mindflayer-token-controller').instance.settings.camera.control);
    if (effective !== (mode === 'default' ? 'focusPlayers' : 'off')) throw new Error('Explicit camera choice was not preserved');
    await previous.dispose();
  }
  console.log('PASS: Beamer camera preserves explicit off and selective reload.');
  await displayContext.close();
  if (process.env.BEAMER_VM === '1') {
    stage = 'installed VM worker';
    await new Promise((resolve, reject) => {
      const child = spawn('ssh', ['-i', 'test/.qemu/id_ed25519', '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes',
        '-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=/dev/null', '-p', '2222', 'root@127.0.0.1',
        'runuser -u elderbrain-kiosk -- python3 /tmp/elderbrain-beamer-installed.py'], { stdio: ['pipe', 'pipe', 'ignore'] });
      let output = '';
      const timer = setTimeout(() => { child.kill(); reject(new Error('VM worker timeout')); }, 110000);
      child.stdout.on('data', data => { output += data; });
      child.on('error', () => { clearTimeout(timer); reject(new Error('VM test unavailable')); });
      child.on('exit', code => {
        clearTimeout(timer);
        if (code === 0 && output.includes('PASS: installed Node worker') && output.includes('PASS: installed player worker')) {
          console.log('PASS: installed VM worker, real Foundry login, Wayland window and cleanup.'); resolve();
        } else reject(new Error('Installed VM worker failed'));
      });
      child.stdin.on('error', () => {});
      child.stdin.end(JSON.stringify({ worldId: world, userId: identifier, password }));
    });
  }
  stage = 'persistent player worker';
  if (process.env.BEAMER_API === '1') {
    stage = 'installed VM API pipeline';
    await new Promise((resolve, reject) => {
      const child = spawn('ssh', ['-i', 'test/.qemu/id_ed25519', '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes',
        '-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=/dev/null', '-p', '2222', 'root@127.0.0.1',
        'node /tmp/elderbrain-beamer-api.mjs'], { stdio: ['pipe', 'pipe', 'ignore'] });
      let output = '';
      const timer = setTimeout(() => { child.kill(); reject(new Error('VM API timeout')); }, 120000);
      child.stdout.on('data', data => { output += data; });
      child.on('error', () => { clearTimeout(timer); reject(new Error('VM API unavailable')); });
      child.on('exit', code => {
        clearTimeout(timer);
        if (code === 0 && output.includes('PASS: authenticated save, root projection') && output.includes('PASS: test pairing removed')) {
          console.log('PASS: installed HTTPS API → private projection → automatic Wayland login → live status, with cleanup.'); resolve();
        } else reject(new Error('VM API pipeline failed'));
      });
      child.stdin.on('error', () => {});
      child.stdin.end(JSON.stringify({ password: fs.readFileSync(process.env.BEAMER_ADMIN_PASSWORD_FILE, 'utf8'),
        beamer: { worldId: world, userId: identifier, password } }));
    });
  }
  stage = 'persistent player worker';
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'elderbrain-beamer-worker-'));
  const controller = new AbortController();
  const states = [];
  const watchdog = setTimeout(() => controller.abort(), 180000);
  try {
    stage = 'persistent profile restart';
    const firstSession = new AbortController();
    const firstStates = [];
    const firstWatchdog = setTimeout(() => firstSession.abort(), 45000);
    try {
      await runBeamer(chromium, { profile, index: 1, headless: true, origin: base,
        credential: { worldId: world, username, password } }, result => {
        firstStates.push(result.state);
        if (firstStates.filter(state => state === 'ready').length === 2) firstSession.abort();
      }, firstSession.signal);
      if (firstStates.filter(state => state === 'ready').length < 2) throw new Error('Initial persistent session failed');
    } finally {
      clearTimeout(firstWatchdog);
      firstSession.abort();
    }
    // A previously authenticated profile must not bypass current credentials.
    stage = 'persistent profile credential rejection';
    const rejectedStates = [];
    const rejected = await runBeamer(chromium, { profile, index: 1, headless: true, origin: base,
      credential: { worldId: world, username, password: randomBytes(24).toString('base64url') } },
    result => rejectedStates.push(result.state), controller.signal);
    if (rejected.state !== 'login-failed' || rejectedStates.includes('ready')) throw new Error('Persistent cookies bypassed password verification');
    console.log('PASS: previously authenticated persistent profile rejects incorrect credentials.');
    stage = 'persistent player worker restart and revocation';
    await runBeamer(chromium, { profile, index: 1, headless: true, origin: base,
      credential: { worldId: world, username, password } }, result => {
      states.push(result.state);
      if (states.filter(state => state === 'ready').length === 2 && result.state === 'ready') {
        void gm.evaluate(async id => {
          const namespace = 'mindflayer-token-controller';
          if (game.world.id !== 'elderbrain-beamer' || game.settings.get(namespace, 'beamerUserId') !== id) throw new Error('Unsafe revocation context');
          await game.settings.set(namespace, 'beamerUserId', '');
        }, identifier).catch(() => controller.abort());
      }
    }, controller.signal);
    if (states.filter(state => state === 'ready').length < 2) throw new Error('Worker did not verify and monitor login');
    if (!states.includes('pairing-required')) throw new Error('Worker did not detect revoked world selection');
    console.log('PASS: persistent player worker restarts with the same profile, verifies login, emits a ready heartbeat, and closes after world selection is revoked.');
  } finally {
    clearTimeout(watchdog);
    controller.abort();
    fs.rmSync(profile, { recursive: true, force: true });
  }
} catch {
  console.error(`Beamer login probe failed at ${stage}; credential-bearing diagnostics suppressed.`);
  process.exitCode = 1;
} finally {
  if (identifier && gm) {
    await gm.evaluate(async id => {
      if (game.world.id !== 'elderbrain-beamer' || !game.user.isGM) throw new Error('Unsafe cleanup context');
      const namespace = 'mindflayer-token-controller';
      if (game.settings.get(namespace, 'beamerUserId') === id) await game.settings.set(namespace, 'beamerUserId', '');
      await game.users.get(id)?.delete();
    }, identifier);
    console.log('Removed temporary Beamer probe user from isolated world.');
  }
  await browser.close();
}
