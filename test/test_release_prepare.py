import json
import fcntl
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test.test_release_assembly as assembly_fixture
import test.test_appliance_release as release_fixture
from release_prepare import prepare

ROOT = Path(__file__).resolve().parents[1]


class ReleasePrepareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        release_fixture.ApplianceReleaseTests.setUpClass()
        cls.addClassCleanup(release_fixture.ApplianceReleaseTests.doClassCleanups)

    def setUp(self):
        fixture = release_fixture.ApplianceReleaseTests()
        fixture.setUp()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bundle = self.root / 'bundle'
        metadata = fixture.value
        del metadata['host']['artifact']
        self.release = assembly_fixture.assembler.assemble(metadata, ROOT, ROOT / 'release/host-files.json',
            self.bundle, fixture.private, fixture.public)
        self.public = fixture.public.read_bytes()
        self.paths = {entry['path']: entry['mode'] for entry in assembly_fixture.assembler.host.entries(ROOT / 'release/host-files.json')}
        self.paths['runtime/VERSION'] = 0o644
        self.destination = self.root / 'releases'
        self.destination.mkdir(mode=0o700)
        self.environment = self.root / 'appliance.env'
        self.environment.write_text('PRIVATE_SETTING=keep-current\n')
        self.calls = []
        self.reject_config = False

    def execute(self, args, **kwargs):
        self.calls.append(args)
        if args[:3] == ['docker', 'image', 'inspect']:
            image = {'Id': 'sha256:' + 'b' * 64, 'RepoDigests': [args[3]], 'Os': 'linux', 'Architecture': 'amd64',
                     'Config': {'Labels': {'org.opencontainers.image.version': '2.0.0',
                         'io.mindflayer.elderbrain.host-api-min': '1', 'io.mindflayer.elderbrain.host-api-max': '2'}}}
            return SimpleNamespace(returncode=0, stdout=json.dumps([image]))
        self.assertEqual(args[-2:], ['config', '--quiet'])
        self.assertTrue(kwargs['check'])
        if self.reject_config:
            raise subprocess.CalledProcessError(1, args)
        return SimpleNamespace(returncode=0)

    def prepare(self, **options):
        return prepare(self.bundle / 'elderbrain-host.tar.zst', (self.bundle / 'manifest.json').read_bytes(),
            (self.bundle / 'manifest.sig').read_bytes(), self.public, self.paths,
            directory=self.destination, platform=self.release['platform'], configuration_schema=1,
            environment_file=self.environment, run=self.execute, **options)

    def test_complete_private_preparation_preserves_live_settings(self):
        receipt = self.prepare()
        final = self.destination / '1.2.3'
        self.assertEqual(receipt['state'], 'code-and-images-prepared')
        self.assertIs(receipt['activationReady'], False)
        self.assertIs(receipt['dependenciesPrepared'], False)
        self.assertEqual(json.loads((final / 'preparation.json').read_text()), receipt)
        self.assertEqual(self.environment.read_text(), 'PRIVATE_SETTING=keep-current\n')
        self.assertNotIn('PRIVATE_SETTING', (final / 'tree/runtime/compose.yaml').read_text())
        self.assertTrue((final / 'elderbrain-host.tar.zst').is_file())
        self.assertEqual(sorted(path.name for path in self.destination.iterdir()), ['.prepare.lock', '1.2.3'])
        self.assertEqual(len(self.calls), 5)

    def test_config_failure_leaves_no_published_release(self):
        self.reject_config = True
        with self.assertRaises(subprocess.CalledProcessError):
            self.prepare()
        self.assertEqual([path.name for path in self.destination.iterdir()], ['.prepare.lock'])

    def test_existing_release_never_overwritten(self):
        self.prepare()
        self.calls.clear()
        with self.assertRaises(FileExistsError):
            self.prepare()
        self.assertEqual(self.calls, [])

    def test_tampered_package_rejected_before_image_activity(self):
        artifact = self.bundle / 'elderbrain-host.tar.zst'
        artifact.write_bytes(b'x' * artifact.stat().st_size)
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertEqual(self.calls, [])
        self.assertFalse((self.destination / '1.2.3').exists())

    def test_low_space_rejected_before_staging_or_docker(self):
        with patch('release_prepare.shutil.disk_usage', return_value=SimpleNamespace(free=0)):
            with self.assertRaisesRegex(ValueError, 'space'):
                self.prepare()
        self.assertEqual(self.calls, [])

    def test_concurrent_preparation_is_excluded(self):
        with (self.destination / '.prepare.lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                self.prepare()
        self.assertEqual(self.calls, [])

    def test_private_directory_required(self):
        self.destination.chmod(0o755)
        with self.assertRaisesRegex(ValueError, 'private canonical'):
            self.prepare()
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
