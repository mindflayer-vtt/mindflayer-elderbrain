import test from 'node:test';
import assert from 'node:assert/strict';
import { beamerReviewAccepted, loginBeamer } from '../../provisioning/graphics/beamer-login.mjs';

function pageFor(users, { afterClickPath, waitError, reviewIssues = [], reviewStatus } = {}) {
  let location = 'about:blank', chosen, submitted = false;
  const game = { version: '14.367', world: { id: 'test-world' },
    users: { filter: fn => users.filter(fn), get: id => users.find(u => u.id === id) },
    canvas: { initialized: true }, modules: new Map([['mindflayer-token-controller',
      { active: true, instance: { modules: { BeamerUsers: { loaded: true,
        selectedId: 'AbCdEf0123456789', status: () => reviewStatus === undefined ? ({
          state: reviewIssues.length ? 'review-required' : 'configured', issues: reviewIssues,
        }) : reviewStatus } } } }]]) };
  return { submitted: () => submitted, chosen: () => chosen,
    route: async () => {}, unroute: async () => {},
    goto: async url => { location = url; }, url: () => location,
    getByText: () => ({ isVisible: async () => false }),
    locator: selector => ({ waitFor: async () => {}, count: async () => 1,
      selectOption: async id => { chosen = id; }, fill: async () => { submitted = true; },
      click: async () => {
        game.user = users.find(user => user.id === chosen);
        if (afterClickPath) location = new URL(afterClickPath, config.origin).href;
      } }),
    waitForFunction: async () => { if (waitError) throw new Error('Timed out waiting for Foundry'); },
    evaluate: async (fn, args) => {
      globalThis.game = game; globalThis.CONST = { USER_ROLES: { PLAYER: 1, TRUSTED: 2 }, USER_PERMISSIONS: {} };
      try { return fn(args); } finally { delete globalThis.game; delete globalThis.CONST; }
    } };
}
const player = { id: 'AbCdEf0123456789', name: 'Beamer', role: 1, isGM: false };
const config = { origin: 'http://127.0.0.1:30000', worldId: 'test-world', username: 'Beamer', password: 'test-only-password' };
test('username resolves to the exact player ID before submission and verification', async () => {
  const page = pageFor([player]);
  const result = await loginBeamer(page, config);
  assert.equal(result.state, 'ready');
  assert.equal(result.userId, player.id);
  assert.equal(page.chosen(), player.id);
});
test('a Trusted Player is accepted as the Beamer user', async () => {
  const trusted = { ...player, role: 2 };
  const page = pageFor([trusted]);
  const result = await loginBeamer(page, config);
  assert.equal(result.state, 'ready');
  assert.equal(result.userId, trusted.id);
});
test('missing, ambiguous and privileged names never submit a password', async () => {
  for (const users of [[], [{ ...player, name: 'beamer' }], [player, { ...player, id: 'OtherId0123456789' }],
    [{ ...player, role: 3 }], [{ ...player, isGM: true }]]) {
    const page = pageFor(users);
    assert.notEqual((await loginBeamer(page, config)).state, 'ready');
    assert.equal(page.submitted(), false);
    assert.equal(page.url(), 'about:blank');
  }
});
test('a slow world after accepted login is retryable, but rejected credentials stay terminal', async () => {
  const loading = pageFor([player], { afterClickPath: '/game', waitError: true });
  assert.deepEqual(await loginBeamer(loading, config), { state: 'unavailable' });
  assert.equal(loading.url(), 'about:blank');
  const rejected = pageFor([player], { waitError: true });
  assert.deepEqual(await loginBeamer(rejected, config), { state: 'login-failed' });
  assert.equal(rejected.url(), 'about:blank');
});
test('an assigned character and token ownership are allowed without ignoring other module warnings', async () => {
  const character = 'Remove the assigned character before adoption';
  const ownership = 'Document ownership requires manual review';
  for (const issues of [[character], [ownership], [character, ownership]]) {
    assert.equal((await loginBeamer(pageFor([player], { reviewIssues: issues }), config)).state, 'ready');
  }
  const unknown = pageFor([player], { reviewIssues: [character, 'Unrecognized safety concern'] });
  assert.equal((await loginBeamer(unknown, config)).state, 'module-review-required');
  assert.equal(unknown.url(), 'about:blank');
  const malformed = pageFor([player], { reviewStatus: null });
  assert.equal((await loginBeamer(malformed, config)).state, 'module-review-required');
  assert.equal(malformed.url(), 'about:blank');
});
test('the shared review policy fails closed for malformed or unexpected status', () => {
  for (const review of [null, {}, { state: 'configured', issues: ['Unknown'] },
    { state: 'review-required', issues: [] }, { state: 'review-required', issues: 'Unknown' },
    { state: 'unknown', issues: [] }]) assert.equal(beamerReviewAccepted(review), false);
});
