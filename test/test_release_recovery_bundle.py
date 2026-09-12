import json
from pathlib import Path
import subprocess
import unittest

import test.test_release_prepare as preparation_fixture
from release_recovery_bundle import install
from release_staging import stage


class RecoveryBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        preparation_fixture.ReleasePrepareTests.setUpClass()
        cls.addClassCleanup(preparation_fixture.ReleasePrepareTests.doClassCleanups)

    def setUp(self):
        self.fixture = preparation_fixture.ReleasePrepareTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.directory = self.root / 'recovery-bundles'
        self.directory.mkdir(mode=0o700)

    def install(self, **options):
        bundle = self.fixture.bundle
        with stage(bundle / 'elderbrain-host.tar.zst', (bundle / 'manifest.json').read_bytes(),
                   (bundle / 'manifest.sig').read_bytes(), self.fixture.public,
                   self.fixture.paths, parent=self.root) as (_, tree):
            return install(tree, self.fixture.paths, directory=self.directory, **options)

    def test_real_isolated_import_and_repeatable_verified_publication(self):
        result = self.install()
        destination = Path(result['directory'])
        self.assertEqual(destination.name, result['id'])
        self.assertEqual(self.install(), result)
        manifest = json.loads((destination / 'bundle.json').read_text())
        self.assertIn('release_recovery.py', manifest['files'])
        self.assertNotIn('appliance.env', manifest['files'])
        self.assertNotIn('VERSION', manifest['files'])
        self.assertEqual({file.stat().st_mode & 0o777 for file in destination.iterdir()}, {0o600})
        # The source staging context is gone; import must still be independent.
        subprocess.run(['/usr/bin/python3', '-I', '-B', '-c',
                        'import sys;sys.path.insert(0,sys.argv[1]);import release_recovery;'
                        'assert callable(release_recovery.recover)', str(destination)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def test_modified_existing_bundle_is_not_overwritten(self):
        result = self.install()
        module = Path(result['directory']) / 'release_recovery.py'
        module.write_text('damaged')
        with self.assertRaisesRegex(ValueError, 'bytes differ'):
            self.install()
        self.assertEqual(module.read_text(), 'damaged')

    def test_failed_import_publishes_no_bundle(self):
        def fail(args, **options):
            raise subprocess.CalledProcessError(1, args)
        with self.assertRaises(subprocess.CalledProcessError):
            self.install(run=fail)
        self.assertEqual([file.name for file in self.directory.iterdir()], ['.install.lock'])

    def test_extra_files_rejected_on_reuse(self):
        result = self.install()
        (Path(result['directory']) / 'unexpected').write_text('extra')
        with self.assertRaisesRegex(ValueError, 'unexpected'):
            self.install()

    def test_public_bundle_parent_is_rejected(self):
        self.directory.chmod(0o755)
        with self.assertRaisesRegex(ValueError, 'private canonical'):
            self.install()


if __name__ == '__main__':
    unittest.main()
