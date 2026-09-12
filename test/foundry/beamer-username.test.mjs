import test from 'node:test';
import assert from 'node:assert/strict';
import { loginBeamer } from '../../provisioning/graphics/beamer-login.mjs';

function pageFor(users) {
  let location = 'about:blank', chosen, submitted = false;
  const game = { version: '14.367', world: { id: 'test-world' },
    users: { filter: fn => users.filter(fn), get: id => users.find(u => u.id === id) },
    canvas: { initialized: true }, modules: new Map([['mindflayer-token-controller',
      { active: true, instance: { modules: { BeamerUsers: { loaded: true,
        selectedId: 'AbCdEf0123456789', status: () => ({ state: 'configured' }) } } } }]]) };
  return { submitted: () => submitted, chosen: () => chosen,
    route: async () => {}, unroute: async () => {},
    goto: async url => { location = url; }, url: () => location,
    getByText: () => ({ isVisible: async () => false }),
    locator: selector => ({ waitFor: async () => {}, count: async () => 1,
      selectOption: async id => { chosen = id; }, fill: async () => { submitted = true; },
      click: async () => { game.user = users.find(user => user.id === chosen); } }),
    waitForFunction: async () => {},
    evaluate: async (fn, args) => {
      globalThis.game = game; globalThis.CONST = { USER_ROLES: { PLAYER: 1 }, USER_PERMISSIONS: {} };
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
test('missing, ambiguous and privileged names never submit a password', async () => {
  for (const users of [[], [{ ...player, name: 'beamer' }], [player, { ...player, id: 'OtherId0123456789' }], [{ ...player, isGM: true }]]) {
    const page = pageFor(users);
    assert.notEqual((await loginBeamer(page, config)).state, 'ready');
    assert.equal(page.submitted(), false);
    assert.equal(page.url(), 'about:blank');
  }
});
