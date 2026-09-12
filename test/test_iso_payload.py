import importlib.util
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('tracked_payload', ROOT / 'iso/tracked-payload.py')
tracked = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tracked)


class IsoPayloadTests(unittest.TestCase):
    def test_opt_in_development_rsync_excludes_secrets_and_keeps_runtime_inputs(self):
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

    def test_production_payload_contains_only_clean_tracked_commit_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository, payload = root / 'repository', root / 'payload'
            repository.mkdir(); payload.mkdir()
            subprocess.run(['git', 'init', '-q'], cwd=repository, check=True)
            subprocess.run(['git', 'config', 'user.name', 'Fixture'], cwd=repository, check=True)
            subprocess.run(['git', 'config', 'user.email', 'fixture@example.test'], cwd=repository, check=True)
            (repository / 'tracked.txt').write_text('reviewed\n')
            subprocess.run(['git', 'add', 'tracked.txt'], cwd=repository, check=True)
            subprocess.run(['git', 'commit', '-qm', 'fixture'], cwd=repository, check=True)
            (repository / 'untracked-secret.txt').write_text('must-not-be-copied')
            result = tracked.stage(repository, payload, '1.2.3', 7)
            self.assertEqual((payload / 'tracked.txt').read_text(), 'reviewed\n')
            self.assertFalse((payload / 'untracked-secret.txt').exists())
            self.assertEqual((payload / 'VERSION').read_text(), '1.2.3\n')
            self.assertEqual(json.loads((payload / 'build-metadata.json').read_text()), result)
            self.assertEqual(result['inputMode'], 'tracked-commit')
            self.assertEqual(result['releaseSequence'], 7)
            identity = result.pop('sourceIdentity')
            encoded = json.dumps(result, sort_keys=True, separators=(',', ':')).encode()
            self.assertEqual(identity, hashlib.sha256(encoded).hexdigest())

    def test_production_payload_rejects_dirty_or_unsupported_tracked_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = root / 'repository'
            repository.mkdir()
            subprocess.run(['git', 'init', '-q'], cwd=repository, check=True)
            subprocess.run(['git', 'config', 'user.name', 'Fixture'], cwd=repository, check=True)
            subprocess.run(['git', 'config', 'user.email', 'fixture@example.test'], cwd=repository, check=True)
            file = repository / 'tracked.txt'
            file.write_text('first\n')
            subprocess.run(['git', 'add', 'tracked.txt'], cwd=repository, check=True)
            subprocess.run(['git', 'commit', '-qm', 'fixture'], cwd=repository, check=True)
            file.write_text('changed\n')
            (root / 'dirty').mkdir()
            with self.assertRaisesRegex(ValueError, 'clean tracked'):
                tracked.stage(repository, root / 'dirty', '1.0.0', 1)
            file.write_text('first\n')
            (repository / 'link').symlink_to('tracked.txt')
            subprocess.run(['git', 'add', 'link'], cwd=repository, check=True)
            subprocess.run(['git', 'commit', '-qm', 'symlink'], cwd=repository, check=True)
            (root / 'linked').mkdir()
            with self.assertRaisesRegex(ValueError, 'unsupported entries'):
                tracked.stage(repository, root / 'linked', '1.0.0', 1)

    def test_semantic_build_identity_rejects_implicit_or_git_versions(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            for version in ('', 'abc123', '1.0', '01.0.0'):
                with self.subTest(version=version), self.assertRaisesRegex(ValueError, 'stable semantic'):
                    tracked.metadata(destination, version, 1, 'a' * 40, 'b' * 40)
            for sequence in (0, -1, True, 2 ** 63):
                with self.subTest(sequence=sequence), self.assertRaisesRegex(ValueError, 'positive 63-bit'):
                    tracked.metadata(destination, '1.0.0', sequence, 'a' * 40, 'b' * 40)

    def test_iso_builder_uses_tracked_payload_by_default_and_labels_dirty_opt_in(self):
        builder = (ROOT / 'iso/build.sh').read_text()
        self.assertIn('python3 "$ROOT/iso/tracked-payload.py"', builder)
        self.assertIn('DEV_ALLOW_DIRTY_WORKTREE', builder)
        self.assertIn('suffix=-dirty', builder)
        self.assertIn('APPLIANCE_VERSION must be a stable semantic version', builder)
        self.assertIn('APPLIANCE_RELEASE_SEQUENCE must be a positive 63-bit integer', builder)
