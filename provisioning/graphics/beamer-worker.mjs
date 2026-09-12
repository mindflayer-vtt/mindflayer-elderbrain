import { loginBeamer } from './beamer-login.mjs';
import { setTimeout as delay } from 'node:timers/promises';
import { pathToFileURL } from 'node:url';

/** One isolated persistent player profile; never an administration profile. */
export async function runBeamer(chromium, config, publish, signal) {
  let context;
  try {
    const env = { ...process.env };
    for (const key of Object.keys(env)) if (/^(DEBUG|PWDEBUG|PW_|PLAYWRIGHT_)/.test(key)) delete env[key];
    context = await chromium.launchPersistentContext(config.profile, {
      executablePath: config.browser, headless: config.headless === true,
      chromiumSandbox: true, env, serviceWorkers: 'block',
      args: [`--class=elderbrain-view-${config.index}`, '--kiosk', '--no-first-run',
        '--no-default-browser-check', '--hide-crash-restore-bubble',
        ...(config.headless ? [] : ['--ozone-platform=wayland', '--enable-features=UseOzonePlatform'])],
    });
    const stop = () => { void context.close().catch(() => {}); };
    signal.addEventListener('abort', stop, { once: true });
    try {
      // Persistent cookies must never skip fresh identity and permission checks.
      await context.clearCookies();
      const pages = context.pages();
      const page = pages[0] || await context.newPage();
      for (const extra of pages.slice(1)) await extra.close();
      const result = await loginBeamer(page, { origin: config.origin, ...config.credential });
      publish(result);
      if (result.state !== 'ready') return result;
      while (!signal.aborted) {
        await delay(5000, undefined, { signal }).catch(() => {});
        if (signal.aborted) break;
        const state = await page.evaluate(({ worldId, userId }) => {
          if (!globalThis.game?.ready || !game.socket?.connected || game.world?.id !== worldId) return 'world-not-running';
          if (game.user?.id !== userId) return 'pairing-required';
          if (game.user.isGM || game.user.role !== CONST.USER_ROLES.PLAYER
            || Object.keys(CONST.USER_PERMISSIONS).some(key => game.user.can(key))) return 'review-required';
          const service = game.modules.get('mindflayer-token-controller')?.instance?.modules.BeamerUsers;
          if (!service?.loaded) return 'module-unavailable';
          if (service.selectedId !== userId) return 'pairing-required';
          if (service.status().state !== 'configured') return 'review-required';
          if (!game.canvas?.initialized) return 'canvas-unavailable';
          return 'ready';
        }, { worldId: config.credential.worldId, userId: result.userId });
        publish({ state });
        if (state !== 'ready') return { state };
      }
      return { state: 'stopped' };
    } finally { signal.removeEventListener('abort', stop); }
  } catch {
    const result = { state: signal.aborted ? 'stopped' : 'unavailable' };
    publish(result);
    return result;
  } finally { await context?.close().catch(() => {}); }
}

async function main() {
  // The launcher writes one bounded JSON packet to a pipe, never command arguments.
  for (const key of Object.keys(process.env)) if (/^(DEBUG|PWDEBUG|PW_|PLAYWRIGHT_)/.test(key)) delete process.env[key];
  let data = '';
  for await (const chunk of process.stdin) {
    data += chunk;
    if (Buffer.byteLength(data) > 8192) throw new Error('Invalid worker input');
  }
  const config = JSON.parse(data);
  if (![0, 1].includes(config.index) || config.headless
    || config.profile !== `/var/lib/mindflayer-elderbrain/browser/profile-${config.index}-player`
    || !['/usr/bin/google-chrome-stable', '/usr/bin/chromium', '/usr/bin/chromium-browser'].includes(config.browser)
    || config.origin !== 'http://127.0.0.1:30000') throw new Error('Invalid worker configuration');
  const controller = new AbortController();
  process.once('SIGTERM', () => controller.abort());
  process.once('SIGINT', () => controller.abort());
  const { chromium } = await import('playwright-core');
  await runBeamer(chromium, config, value => {
    process.stdout.write(JSON.stringify({ state: value.state, observedAt: Date.now() }) + '\n');
  }, controller.signal);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch(() => { process.stdout.write('{"state":"unavailable"}\n'); process.exitCode = 1; });
}
