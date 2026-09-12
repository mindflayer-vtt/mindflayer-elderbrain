// Explicit disposable-VM fixture. Never use this account for a shipped appliance.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { randomBytes } from 'node:crypto';
import { AuthStore } from '../server/utils/auth.ts';

const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'elderbrain-vm-auth-'));
let verification = '';
const auth = new AuthStore(directory, async (_smtp, _to, _subject, text) => {
  verification = /Verification code: (\d+)/.exec(text)![1]!;
});
const initial = fs.readFileSync(path.join(directory, 'secrets/initial-password'), 'utf8').trim();
const password = randomBytes(24).toString('hex');
const session = auth.login('admin', initial, 'disposable-vm');
auth.changePassword(session.id, initial, password);
await auth.configureEmail('vm-test@example.invalid', { host: 'smtp.example.invalid', port: 587, secure: false, from: 'vm-test@example.invalid' });
auth.verifyEmail(verification);
fs.writeFileSync(path.join(directory, 'password'), password, { mode: 0o600 });
console.log(directory);
