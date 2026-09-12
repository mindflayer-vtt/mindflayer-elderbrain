/** Run only in a dedicated display browser context; never attach to an admin tab.
 * The caller owns browser lifecycle, private credential loading and status persistence.
 * No diagnostics from the browser/automation library may be logged by the caller.
 */
export async function loginBeamer(page, { origin, worldId, userId, username, password }, timeout = 30000) {
  let target;
  try {
    target = new URL(origin);
    if (target.username || target.password || target.pathname !== '/' || target.search || target.hash
      || !(target.protocol === 'https:' || (target.protocol === 'http:' && ['127.0.0.1', '[::1]'].includes(target.hostname)))
      || !/^[A-Za-z0-9_-]{1,128}$/.test(worldId)
      || (username !== undefined
        ? typeof username !== 'string' || !username.trim() || username.length > 128 || /[\x00-\x1f\x7f]/.test(username)
        : !/^[A-Za-z0-9]{16}$/.test(userId))
      || typeof password !== 'string' || password.length < 12 || password.length > 256) return { state: 'pairing-required' };
  } catch { return { state: 'pairing-required' }; }
  let state = 'unavailable';
  const guard = route => {
    // Prevent redirects or form submissions from carrying login data off-origin.
    const request = route.request();
    if (new URL(request.url()).origin !== target.origin
      || request.url().includes(password) || request.url().includes(encodeURIComponent(password))) return route.abort();
    return route.continue();
  };
  await page.route('**/*', guard);
  try {
    await page.goto(`${target.origin}/join`, { timeout, waitUntil: 'domcontentloaded' });
    if (new URL(page.url()).origin !== target.origin) return { state: 'origin-mismatch' };
    if (['/setup', '/license', '/auth'].includes(new URL(page.url()).pathname)) return { state: 'world-not-running' };
    // Foundry 14 also serves an HTTP-200 /join error page when no world is active.
    if (await page.getByText('There is currently no active game session.', { exact: false }).isVisible()) return { state: 'world-not-running' };
    await page.locator('input[name="password"]').waitFor({ timeout });
    const before = await page.evaluate(({ worldId, userId, username }) => {
      if (globalThis.game?.world?.id !== worldId) return { state: 'world-not-running' };
      if (game.version !== '14.367') return { state: 'unsupported-version' };
      const matches = username !== undefined ? game.users?.filter(user => user.name === username) : null;
      if (matches && matches.length !== 1) return { state: 'pairing-required' };
      const user = matches ? matches[0] : game.users?.get(userId);
      if (!user) return { state: 'pairing-required' };
      if (user.isGM || user.role !== CONST.USER_ROLES.PLAYER) return { state: 'review-required' };
      return { state: 'join', name: user.name, userId: user.id };
    }, { worldId, userId, username });
    if (before.state !== 'join') return { state: before.state };
    userId = before.userId;
    const selector = page.locator('select[name="userid"], select[name="user"]');
    if (await selector.count()) await selector.selectOption(userId, { force: true, timeout });
    else await page.locator('input[name="username"]').fill(before.name, { timeout });
    await page.locator('input[name="password"]').fill(password, { timeout });
    state = 'login-failed';
    await page.locator('button[name="join"]').click({ timeout });
    await page.waitForFunction(() => globalThis.game?.ready === true, null, { timeout });
    const result = await page.evaluate(({ worldId, userId }) => {
      if (game.world?.id !== worldId || game.user?.id !== userId) return { state: 'pairing-required' };
      if (game.user.isGM || game.user.role !== CONST.USER_ROLES.PLAYER
        || Object.keys(CONST.USER_PERMISSIONS).some(key => game.user.can(key))) return { state: 'review-required' };
      const module = game.modules.get('mindflayer-token-controller');
      const service = module?.instance?.modules.BeamerUsers;
      if (!module?.active || !service?.loaded) return { state: 'module-unavailable' };
      if (service.selectedId !== userId) return { state: 'pairing-required' };
      if (service.status().state !== 'configured') return { state: 'review-required' };
      return { state: game.canvas?.initialized ? 'ready' : 'canvas-unavailable' };
    }, { worldId, userId });
    state = result.state;
    return { ...result, userId };
  } catch {
    return { state };
  } finally {
    // Failed verification must not leave a partially authorized page on the screen.
    if (state !== 'ready') await page.goto('about:blank').catch(() => {});
    await page.unroute('**/*', guard);
  }
}
