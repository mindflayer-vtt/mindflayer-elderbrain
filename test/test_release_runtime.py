import hashlib
import json
import shutil
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test.test_release_prepare as preparation_fixture
from release_runtime import candidate


class RuntimeCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        preparation_fixture.ReleasePrepareTests.setUpClass()
        cls.addClassCleanup(preparation_fixture.ReleasePrepareTests.doClassCleanups)

    def setUp(self):
        self.fixture = preparation_fixture.ReleasePrepareTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.signed_dependencies()
        self.root = self.fixture.root
        self.prepared = self.root / '1.2.3'
        shutil.copytree(self.fixture.bundle, self.prepared)
        self.prepared.chmod(0o700)
        self.dependencies = self.root / 'installed'
        self.dependencies.mkdir(mode=0o700)
        self.prefix = self.dependencies / '1.2.3'
        self.prefix.mkdir(mode=0o700)
        modules = self.prefix / 'beamer/node_modules'
        (modules / 'playwright-core').mkdir(parents=True)
        (modules / 'playwright-core/cli.js').write_text('fixture code')
        (modules / '.bin').mkdir()
        (modules / '.bin/playwright-core').symlink_to('../playwright-core/cli.js')
        self.receipt = {'state': 'dependencies-installed', 'version': '1.2.3',
            'prefix': str(self.prefix), 'dependenciesPrepared': True,
            'manifestSha256': hashlib.sha256((self.prepared / 'manifest.json').read_bytes()).hexdigest()}
        (self.prefix / 'installation.json').write_text(json.dumps(self.receipt))
        self.state = self.root / 'state'
        settings = self.state / 'host/runtime'
        settings.mkdir(parents=True)
        (settings / 'appliance.env').write_text('PRIVATE_SETTING=preserve\n')
        (settings / 'appliance.env').chmod(0o600)
        (settings / 'sway.conf').write_text('preserved sway configuration\n')
        self.offline = []
        self.fail_offline = False

    def execute(self, args, **options):
        if args[0] == 'unshare':
            self.offline.append(args)
            self.assertEqual(args[:3], ['unshare', '--net', '--'])
            self.assertTrue(options['check'])
            if self.fail_offline:
                raise subprocess.CalledProcessError(1, args)
            return SimpleNamespace(returncode=0)
        return self.fixture.execute(args, **options)

    def candidate(self):
        return candidate(self.prepared, self.fixture.public, self.fixture.paths,
            dependency_directory=self.dependencies, state=self.state,
            platform=self.fixture.release['platform'], configuration_schema=1,
            parent=self.root, run=self.execute)

    def test_rebuilds_signed_code_and_links_settings_without_trusting_loose_tree(self):
        loose = self.prepared / 'tree/runtime'
        loose.mkdir(parents=True)
        (loose / 'management-server').write_text('untrusted loose file')
        with patch('release_runtime.persistent_identity', return_value={'data_uuid': 'fixture'}), self.candidate() as (release, tree):
            self.assertEqual(release['version'], '1.2.3')
            self.assertNotEqual((tree / 'runtime/management-server').read_text(), 'untrusted loose file')
            self.assertEqual((tree / 'runtime/appliance.env').readlink(), self.state / 'host/runtime/appliance.env')
            self.assertEqual((tree / 'runtime/serial-venv').readlink(), self.prefix / 'serial-venv')
            self.assertNotIn('PRIVATE_SETTING', (tree / 'runtime/compose.yaml').read_text())
            self.assertFalse((tree / 'runtime/beamer/node_modules').is_symlink())
            self.assertEqual((tree / 'runtime/beamer/node_modules/.bin/playwright-core').read_text(), 'fixture code')
            self.assertEqual((tree / 'runtime').stat().st_mode & 0o777, 0o755)
            self.assertEqual(self.prefix.stat().st_mode & 0o777, 0o700)
            self.assertEqual((self.state / 'host/runtime/appliance.env').stat().st_mode & 0o777, 0o600)
        self.assertFalse(tree.exists())
        self.assertEqual(len(self.offline), 8)
        self.assertEqual(len(self.fixture.calls), 5)
        self.assertEqual((self.state / 'host/runtime/appliance.env').read_text(), 'PRIVATE_SETTING=preserve\n')

    def test_tampered_archive_rejected_before_runtime_execution(self):
        archive = self.prepared / 'elderbrain-host.tar.zst'
        archive.write_bytes(b'x' * archive.stat().st_size)
        with patch('release_runtime.persistent_identity', return_value={'data_uuid': 'fixture'}):
            with self.assertRaises(ValueError), self.candidate():
                pass
        self.assertEqual(self.offline, [])

    def test_dependency_receipt_must_match_manifest(self):
        self.receipt['manifestSha256'] = '0' * 64
        (self.prefix / 'installation.json').write_text(json.dumps(self.receipt))
        with patch('release_runtime.persistent_identity', return_value={'data_uuid': 'fixture'}):
            with self.assertRaisesRegex(ValueError, 'does not belong'), self.candidate():
                pass
        self.assertEqual(self.offline, [])

    def test_missing_storage_rejected_before_runtime_execution(self):
        with patch('release_runtime.persistent_identity', return_value=None):
            with self.assertRaisesRegex(ValueError, 'persistent storage'), self.candidate():
                pass
        self.assertEqual(self.offline, [])

    def test_changed_storage_rejected_before_yield(self):
        with patch('release_runtime.persistent_identity', side_effect=[{'data_uuid': 'old'}, {'data_uuid': 'new'}]):
            with self.assertRaisesRegex(ValueError, 'storage changed'), self.candidate():
                pass

    def test_broken_environment_rejected_before_image_work(self):
        self.fail_offline = True
        with patch('release_runtime.persistent_identity', return_value={'data_uuid': 'fixture'}):
            with self.assertRaises(subprocess.CalledProcessError), self.candidate():
                pass
        self.assertEqual(self.fixture.calls, [])

    def test_browser_module_escape_cannot_copy_private_configuration(self):
        (self.prefix / 'beamer/node_modules/escape').symlink_to(self.state / 'host/runtime/appliance.env')
        with patch('release_runtime.persistent_identity', return_value={'data_uuid': 'fixture'}):
            with self.assertRaisesRegex(ValueError, 'link escapes'), self.candidate():
                pass

    def test_writable_browser_code_is_rejected(self):
        (self.prefix / 'beamer/node_modules/playwright-core/cli.js').chmod(0o666)
        with patch('release_runtime.persistent_identity', return_value={'data_uuid': 'fixture'}):
            with self.assertRaisesRegex(ValueError, 'permissions'), self.candidate():
                pass


if __name__ == '__main__':
    unittest.main()
