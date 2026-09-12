from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class IsoPayloadTests(unittest.TestCase):
    def test_real_rsync_excludes_development_secrets_and_keeps_runtime_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source'
            target = Path(directory) / 'payload'
            target.mkdir()
            private = ['.env', '.env.production', 'setup/.env.local', 'example.secret',
                       'secrets.json', '.agents/session.json', '.codex/settings.json',
                       '.ssh/id_ed25519', '.pki/nssdb/key4.db', 'config/private/smtp.json',
                       'test/.qemu/id_ed25519', 'local.mk', 'setup/node_modules/package/index.js',
                       'setup/.output/server/index.mjs', 'test/__pycache__/cached.pyc']
            public = ['provisioning/install.sh', 'provisioning/graphics/package-lock.json',
                      'setup/package-lock.json', 'setup/app/app.vue', 'appliance/lib/network_worker.py',
                      'config/defaults/appliance.env', 'config/defaults/smtp.example.json',
                      'config/defaults/keypad-signing-public.pem', 'compose/compose.yaml']
            for name in private + public:
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('private-canary' if name in private else 'runtime-input')
            subprocess.run(['rsync', '-a', '--exclude-from=' + str(ROOT / 'iso/payload.exclude'),
                            str(source) + '/', str(target) + '/'], check=True)
            for name in private:
                with self.subTest(excluded=name):
                    self.assertFalse((target / name).exists())
            for name in public:
                with self.subTest(included=name):
                    self.assertEqual((target / name).read_text(), 'runtime-input')
