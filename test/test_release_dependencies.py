import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from . import test_appliance_release as release_fixture
from . import test_release_assembly as assembly_fixture
from release_dependencies import install
from release_prepare import DEPENDENCY_INPUTS


class DependencyInstallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        release_fixture.ApplianceReleaseTests.setUpClass()
        cls.addClassCleanup(release_fixture.ApplianceReleaseTests.doClassCleanups)

    def setUp(self):
        self.fixture = release_fixture.ApplianceReleaseTests()
        self.fixture.setUp()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        inputs = self.root / 'inputs'
        files = {}
        payload = b'command-construction-fixture-not-installable'
        for name in ('wheels/example-1.0-py3-none-any.whl', 'node/playwright-core-1.63.0.tgz'):
            file = inputs / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(payload)
            files[name] = {'size': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()}
        lock = {'packages': {'': {}, 'node_modules/playwright-core': {
            'version': '1.63.0', 'integrity': 'sha512-' + base64.b64encode(hashlib.sha512(payload).digest()).decode()}}}
        mapping = []
        hashes = {}
        for source, target in DEPENDENCY_INPUTS.items():
            file = self.source / source
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(json.dumps(lock) if source.endswith('.json') else 'example==1.0\n')
            hashes[source] = hashlib.sha256(file.read_bytes()).hexdigest()
            mapping.append({'source': source, 'path': target, 'mode': 0o644})
        self.inventory = self.root / 'inventory.json'
        self.inventory.write_text(json.dumps(mapping))
        self.paths = {entry['path']: entry['mode'] for entry in mapping}
        self.paths['runtime/VERSION'] = 0o644
        (inputs / 'dependencies.json').write_text(json.dumps({'format': 1,
            'platform': self.fixture.value['platform'], 'python': '3.14.4', 'files': files, 'inputs': hashes}))
        metadata = deepcopy(self.fixture.value)
        metadata['format'] = 2
        del metadata['host']['artifact']
        self.bundle = self.root / 'bundle'
        assembly_fixture.assembler.assemble(metadata, self.source, self.inventory, self.bundle,
            self.fixture.private, self.fixture.public, dependency_directory=inputs)
        self.destination = self.root / 'installed'
        self.destination.mkdir(mode=0o700)
        self.calls = []
        self.fail_at = None

    def execute(self, command, **options):
        self.calls.append((command, options))
        if self.fail_at == len(self.calls):
            raise subprocess.CalledProcessError(1, command)
        # Fake only the empty environment directories; no claim of real install.
        if 'venv' in command:
            Path(command[-1]).mkdir()
        return SimpleNamespace(returncode=0)

    def install(self):
        with patch('release_dependencies.platform.freedesktop_os_release',
                   return_value={'ID': 'ubuntu', 'VERSION_ID': '26.04'}), \
                patch('release_dependencies.platform.machine', return_value='x86_64'), \
                patch('release_dependencies.sys.version_info', (3, 14, 4)):
            return install(self.bundle / 'elderbrain-host.tar.zst', self.bundle / 'elderbrain-dependencies.tar.zst',
                (self.bundle / 'manifest.json').read_bytes(), (self.bundle / 'manifest.sig').read_bytes(),
                self.fixture.public.read_bytes(), self.paths, directory=self.destination,
                configuration_schema=1, run=self.execute)

    def test_commands_are_offline_and_prefix_is_final(self):
        receipt = self.install()
        final = self.destination / '1.2.3'
        self.assertEqual(receipt['prefix'], str(final))
        self.assertTrue(receipt['dependenciesPrepared'])
        self.assertFalse(receipt['activationReady'])
        self.assertEqual(json.loads((final / 'installation.json').read_text()), receipt)
        self.assertEqual(len(self.calls), 12)
        for command, options in self.calls:
            self.assertEqual(command[:3], ['unshare', '--net', '--'])
            self.assertTrue(options['check'])
            self.assertNotIn('PYTHONPATH', options['env'])
            self.assertNotEqual(options['env']['npm_config_userconfig'], options['env']['npm_config_globalconfig'])
            self.assertEqual(options['timeout'], 300)
            if 'venv' in command:
                self.assertTrue(command[-1].startswith(str(final) + '/'))
            if 'pip' in command and 'install' in command:
                for flag in ('--no-index', '--no-deps', '--only-binary=:all:', '--isolated'):
                    self.assertIn(flag, command)
            if '/usr/bin/npm' in command:
                self.assertIn('--offline', command)
                self.assertIn('--ignore-scripts', command)

    def test_failure_retains_prefix_without_completion_and_refuses_retry(self):
        self.fail_at = 2
        with self.assertRaises(subprocess.CalledProcessError):
            self.install()
        final = self.destination / '1.2.3'
        self.assertTrue(final.is_dir())
        self.assertFalse((final / 'installation.json').exists())
        self.calls.clear()
        with self.assertRaises(FileExistsError):
            self.install()
        self.assertEqual(self.calls, [])

    def test_tampered_dependency_never_executes_or_claims_prefix(self):
        archive = self.bundle / 'elderbrain-dependencies.tar.zst'
        archive.write_bytes(b'x' * archive.stat().st_size)
        with self.assertRaises(ValueError):
            self.install()
        self.assertEqual(self.calls, [])
        self.assertFalse((self.destination / '1.2.3').exists())

    def test_low_space_never_executes(self):
        with patch('release_dependencies.shutil.disk_usage', return_value=SimpleNamespace(free=0)):
            with self.assertRaisesRegex(ValueError, 'space'):
                self.install()
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
