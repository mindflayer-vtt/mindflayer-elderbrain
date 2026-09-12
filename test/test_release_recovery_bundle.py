import json
import os
import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

import test.test_release_prepare as preparation_fixture
from release_recovery_bundle import active, install, select
from release_staging import stage
from backup_service import Maintenance, save_record

spec = importlib.util.spec_from_file_location('recovery_launcher', Path(__file__).resolve().parents[1] / 'provisioning/update/recovery-launcher.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class RecoveryBundleTests(unittest.TestCase):
    def test_job_launcher_uses_verified_worker_and_matching_inherited_descriptor(self):
        result = self.install()
        select(result['id'], directory=self.directory, maintenance=Maintenance(self.root / 'maintenance', None))
        jobs = self.root / 'jobs'
        jobs.mkdir(mode=0o700)
        identity = 'c' * 32
        save_record(jobs / (identity + '.json'), {'id': identity, 'kind': 'update', 'state': 'queued'})
        fd = os.open(jobs / (identity + '.lock'), os.O_CREAT | os.O_RDWR, 0o600)
        self.addCleanup(os.close, fd)
        with patch.object(launcher, 'JOBS', jobs), patch.object(launcher.os, 'execve') as execute:
            launcher.launch('job', self.directory, job=identity, lock_fd=fd)
            args = execute.call_args.args[1]
            self.assertEqual(args[3:], [str(Path(result['directory']) / 'host_jobs.py'),
                'worker', str(jobs), identity, str(fd), '-1'])
            execute.reset_mock()
            other = os.open(jobs / 'other.lock', os.O_CREAT | os.O_RDWR, 0o600)
            try:
                with self.assertRaisesRegex(ValueError, 'does not own'):
                    launcher.launch('job', self.directory, job=identity, lock_fd=other)
            finally:
                os.close(other)
            execute.assert_not_called()

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

    def test_selection_and_verified_launcher_use_only_stable_bundle(self):
        result = self.install()
        maintenance = Maintenance(self.root / 'maintenance', None)
        select(result['id'], directory=self.directory, maintenance=maintenance)
        self.assertEqual(active(directory=self.directory, expected=result['id']), {'bundle': result['id']})
        with self.assertRaisesRegex(ValueError, 'no longer active'):
            active(directory=self.directory, expected='a' * 64)
        expected = Path(result['directory']) / 'release_recovery.py'
        self.assertEqual(launcher.selected(self.directory), expected)
        with patch.object(launcher.os, 'execve') as execute:
            launcher.launch('files', self.directory)
        execute.assert_called_once_with('/usr/bin/python3', ['/usr/bin/python3', '-I', '-B', str(expected), 'files'],
                                        {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C.UTF-8'})

    def test_unfinished_maintenance_preserves_active_selection(self):
        result = self.install()
        maintenance = Maintenance(self.root / 'maintenance', None)
        select(result['id'], directory=self.directory, maintenance=maintenance)
        before = (self.directory / 'active.json').read_bytes()
        save_record(maintenance.journal, {'operation': 'update', 'state': 'files-recovered'})
        with self.assertRaisesRegex(RuntimeError, 'unfinished maintenance'):
            select('a' * 64, directory=self.directory, maintenance=maintenance)
        self.assertEqual((self.directory / 'active.json').read_bytes(), before)

    def test_failed_selection_window_never_publishes_candidate(self):
        from release_recovery_bundle import selection_window
        first = self.install()
        select(first['id'], directory=self.directory, maintenance=Maintenance(self.root / 'maintenance', None))
        before = (self.directory / 'active.json').read_bytes()
        bundle = self.fixture.bundle
        with stage(bundle / 'elderbrain-host.tar.zst', (bundle / 'manifest.json').read_bytes(),
                   (bundle / 'manifest.sig').read_bytes(), self.fixture.public,
                   self.fixture.paths, parent=self.root) as (_, tree):
            module = tree / 'runtime/release_recovery.py'
            module.write_bytes(module.read_bytes() + b'\n# second candidate\n')
            second = install(tree, self.fixture.paths, directory=self.directory)
        with self.assertRaisesRegex(RuntimeError, 'injected failure'):
            with selection_window(second['id'], directory=self.directory,
                                  maintenance=Maintenance(self.root / 'maintenance', None)):
                raise RuntimeError('injected failure')
        self.assertEqual((self.directory / 'active.json').read_bytes(), before)

    def test_launcher_rejects_tampering_before_execution(self):
        result = self.install()
        select(result['id'], directory=self.directory, maintenance=Maintenance(self.root / 'maintenance', None))
        (Path(result['directory']) / 'release_recovery.py').write_text('bad code')
        with patch.object(launcher.os, 'execve') as execute:
            with self.assertRaises(ValueError):
                launcher.launch('finish', self.directory)
        execute.assert_not_called()

    def test_launcher_rejects_unsafe_selector_and_public_module(self):
        result = self.install()
        maintenance = Maintenance(self.root / 'maintenance', None)
        select(result['id'], directory=self.directory, maintenance=maintenance)
        save_record(self.directory / 'active.json', {'format': 1, 'bundle': '../escape'})
        with self.assertRaisesRegex(ValueError, 'selection'):
            launcher.selected(self.directory)
        select(result['id'], directory=self.directory, maintenance=maintenance)
        (Path(result['directory']) / 'release_recovery.py').chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'private'):
            launcher.selected(self.directory)

    def test_storage_phase_uses_verified_guard_outside_live_runtime(self):
        result = self.install()
        select(result['id'], directory=self.directory, maintenance=Maintenance(self.root / 'maintenance', None))
        with patch.object(launcher.os, 'execve') as execute:
            launcher.launch('storage', self.directory)
        argv = execute.call_args.args[1]
        self.assertEqual(argv, ['/usr/bin/python3', '-I', '-B', str(Path(result['directory']) / 'storage_guard.py')])


if __name__ == '__main__':
    unittest.main()
