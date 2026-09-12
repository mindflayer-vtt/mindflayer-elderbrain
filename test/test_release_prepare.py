import json
import hashlib
from copy import deepcopy
import fcntl
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test.test_release_assembly as assembly_fixture
import test.test_appliance_release as release_fixture
from release_prepare import prepare, DEPENDENCY_INPUTS

ROOT = Path(__file__).resolve().parents[1]


class ReleasePrepareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        release_fixture.ApplianceReleaseTests.setUpClass()
        cls.addClassCleanup(release_fixture.ApplianceReleaseTests.doClassCleanups)

    def setUp(self):
        fixture = release_fixture.ApplianceReleaseTests()
        fixture.setUp()
        self.fixture = fixture
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

    def signed_dependencies(self, *, mismatch=False, target=None):
        inputs = self.root / 'dependency-source'
        files = {}
        for name in ('wheels/example-1.0-py3-none-any.whl', 'node/playwright-core-1.63.0.tgz'):
            file = inputs / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(b'fixture-not-installable')
            files[name] = {'size': file.stat().st_size, 'sha256': hashlib.sha256(file.read_bytes()).hexdigest()}
        hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in DEPENDENCY_INPUTS}
        if mismatch:
            hashes['provisioning/graphics/package-lock.json'] = '0' * 64
        (inputs / 'dependencies.json').write_text(json.dumps({
            'format': 1, 'platform': self.release['platform'], 'python': target or '3.14.4',
            'files': files, 'inputs': hashes, 'offlineInstallVerified': True}))
        metadata = deepcopy(self.release)
        metadata['format'] = 2
        del metadata['host']['artifact']
        self.bundle = self.root / 'complete-bundle'
        self.release = assembly_fixture.assembler.assemble(metadata, ROOT, ROOT / 'release/host-files.json',
            self.bundle, self.fixture.private, self.fixture.public, dependency_directory=inputs)
        return self.bundle / 'elderbrain-dependencies.tar.zst'

    def test_signed_dependency_inputs_retained_but_not_activation_ready(self):
        archive = self.signed_dependencies()
        receipt = self.prepare(dependency_archive=archive)
        final = self.destination / '1.2.3'
        self.assertTrue(receipt['dependencyInputsVerified'])
        self.assertFalse(receipt['dependenciesPrepared'])
        self.assertFalse(receipt['activationReady'])
        self.assertEqual((final / archive.name).read_bytes(), archive.read_bytes())
        for name in self.release['dependencies']['files']:
            self.assertEqual((final / 'dependency-inputs' / name).read_bytes(),
                             (self.root / 'dependency-source' / name).read_bytes())

    def test_missing_signed_dependency_archive_rejected_before_docker(self):
        self.signed_dependencies()
        with self.assertRaisesRegex(ValueError, 'Dependency archive'):
            self.prepare()
        self.assertEqual(self.calls, [])

    def test_unsigned_extra_dependency_archive_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Dependency archive'):
            self.prepare(dependency_archive=self.root / 'unsigned.tar.zst')
        self.assertEqual(self.calls, [])

    def test_dependency_host_lock_mismatch_rejected_before_docker(self):
        archive = self.signed_dependencies(mismatch=True)
        with self.assertRaisesRegex(ValueError, 'Dependency inputs differ'):
            self.prepare(dependency_archive=archive)
        self.assertEqual(self.calls, [])
        self.assertFalse((self.destination / '1.2.3').exists())

    def test_tampered_dependency_archive_rejected_before_docker(self):
        archive = self.signed_dependencies()
        archive.write_bytes(b'x' * archive.stat().st_size)
        with self.assertRaises(ValueError):
            self.prepare(dependency_archive=archive)
        self.assertEqual(self.calls, [])
        self.assertFalse((self.destination / '1.2.3').exists())

    def test_invalid_python_patch_rejected_before_docker(self):
        archive = self.signed_dependencies(target='3.14.invalid')
        with self.assertRaisesRegex(ValueError, 'build target'):
            self.prepare(dependency_archive=archive)
        self.assertEqual(self.calls, [])

    def test_offline_installation_links_stable_prefix_without_live_settings(self):
        archive = self.signed_dependencies()
        dependency_directory = self.root / 'dependencies-installed'
        dependency_directory.mkdir(mode=0o700)
        prefix = dependency_directory / '1.2.3'

        def installed(host_archive, dependency_archive, manifest, signature, public_key, paths, **options):
            self.assertEqual(host_archive.read_bytes(), (self.bundle / 'elderbrain-host.tar.zst').read_bytes())
            self.assertEqual(dependency_archive.read_bytes(), archive.read_bytes())
            self.assertEqual(options['directory'], dependency_directory)
            for name in ('serial-venv', 'borgmatic-venv', 'beamer/node_modules'):
                (prefix / name).mkdir(parents=True, exist_ok=True)
            return {'prefix': str(prefix), 'version': '1.2.3', 'dependenciesPrepared': True,
                    'manifestSha256': hashlib.sha256(manifest).hexdigest()}

        with patch('release_dependencies.install', side_effect=installed) as installer:
            receipt = self.prepare(dependency_archive=archive, dependency_directory=dependency_directory)
        installer.assert_called_once()
        final = self.destination / '1.2.3/tree/runtime'
        self.assertEqual(receipt['state'], 'runtime-prepared')
        self.assertTrue(receipt['dependenciesPrepared'])
        self.assertFalse(receipt['activationReady'])
        self.assertEqual(receipt['dependencyPrefix'], str(prefix))
        for name in ('serial-venv', 'borgmatic-venv', 'beamer/node_modules'):
            self.assertTrue((final / name).is_symlink())
            self.assertEqual((final / name).resolve(), prefix / name)
        self.assertFalse((final / 'appliance.env').exists())
        self.assertFalse((final / 'sway.conf').exists())
        self.assertEqual(self.environment.read_text(), 'PRIVATE_SETTING=keep-current\n')

    def test_offline_installation_failure_does_not_publish_runtime(self):
        archive = self.signed_dependencies()
        with patch('release_dependencies.install', side_effect=RuntimeError('offline check failed')):
            with self.assertRaisesRegex(RuntimeError, 'offline check failed'):
                self.prepare(dependency_archive=archive, dependency_directory=self.root / 'dependencies-installed')
        self.assertFalse((self.destination / '1.2.3').exists())

    def test_dependency_prefix_cannot_be_nested_in_preparation_tree(self):
        archive = self.signed_dependencies()
        with self.assertRaisesRegex(ValueError, 'separate'):
            self.prepare(dependency_archive=archive, dependency_directory=self.destination / 'dependencies')
        self.assertEqual(self.calls, [])

    def test_installer_receipt_mismatch_does_not_publish_runtime(self):
        archive = self.signed_dependencies()
        with patch('release_dependencies.install', return_value={'dependenciesPrepared': True}):
            with self.assertRaisesRegex(ValueError, 'did not complete'):
                self.prepare(dependency_archive=archive, dependency_directory=self.root / 'dependencies-installed')
        self.assertFalse((self.destination / '1.2.3').exists())


if __name__ == '__main__':
    unittest.main()
