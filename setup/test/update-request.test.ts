import test from 'node:test';
import assert from 'node:assert/strict';
import { updateRequest } from '../server/utils/update-request';

const selected = { version: '1.2.3', manifestSha256: 'a'.repeat(64), confirmUpdate: true, confirmDowntime: true };
test('update request retains exact version, digest and explicit confirmations', () => {
  assert.deepEqual(updateRequest(selected), selected);
});
test('update request rejects paths, commands, unknown fields and implicit confirmation', () => {
  for (const value of [null, [], {}, { ...selected, path: '/tmp/release' },
    { ...selected, confirmUpdate: 1 }, { ...selected, confirmDowntime: 'true' },
    { ...selected, version: '../1.2.3' }, { ...selected, version: '01.2.3' },
    { ...selected, version: '1.2.3\nreboot' }, { ...selected, version: '1.2.3\n' },
    { ...selected, manifestSha256: 'A'.repeat(64) }]) assert.throws(() => updateRequest(value));
});
