from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test.test_appliance_release
from update_job import run_update


class UpdateWorkerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.state = self.root / 'var/lib/mindflayer-elderbrain'
        self.state.mkdir(parents=True)
        trust = self.root / 'etc/elderbrain'
        trust.mkdir(parents=True)
        (trust / 'release-inventory.json').write_text(json.dumps({'runtime/worker.py': 0o644}))
        (trust / 'release-public.pem').write_text('pinned key')
        releases = self.root / 'var/lib/elderbrain-releases'
        releases.mkdir(mode=0o700)
        (releases / 'prepared').mkdir(mode=0o700)
        self.prepared = releases / 'prepared/1.2.3'
        self.prepared.mkdir(mode=0o700)
        (releases / 'staging').mkdir(mode=0o700)
        dependencies = self.root / 'usr/lib/elderbrain-dependencies'
        dependencies.mkdir(mode=0o700, parents=True)
        (self.prepared / 'manifest.json').write_bytes(b'manifest')
        (self.prepared / 'manifest.sig').write_bytes(b'signature')
        self.request = {'version': '1.2.3', 'manifestSha256': hashlib.sha256(b'manifest').hexdigest(),
                        'confirmUpdate': True, 'confirmDowntime': True}
        self.enterContext(patch('update_job.persistent_identity', return_value='fixture'))
        self.verify = self.enterContext(patch('update_job.verify', return_value={
            'format': 2, 'version': '1.2.3', 'recoveryApi': 1}))
        self.enterContext(patch('update_job.require_compatible'))
        self.prepare_recovery = self.enterContext(patch('update_job.prepare_candidate', return_value={
            'active': 'b' * 64, 'candidate': 'c' * 64}))
        self.commit_recovery = self.enterContext(patch('update_job.commit_candidate'))
        self.apply = self.enterContext(patch('update_job.activate', return_value={'state': 'completed'}))
        self.open = False
        @contextmanager
        def staged(*args, **options):
            self.open = True
            try:
                yield {}, self.root / 'authenticated'
            finally:
                self.open = False
        self.enterContext(patch('update_job.stage', side_effect=staged))
        self.progress = []

    def run_update(self):
        return run_update(self.state, 'a' * 32, self.request, progress=self.progress.append, host_root=self.root)

    def test_fixed_paths_pinned_confirmation_and_owned_admission_are_wired(self):
        def apply(*args, **options):
            self.assertTrue(self.open)
            self.assertEqual(args[0], self.prepared)
            self.assertEqual(args[1], b'pinned key')
            self.assertEqual(options['job_owner'], 'a' * 32)
            self.assertEqual(options['expected_manifest_sha256'], self.request['manifestSha256'])
            self.assertEqual(options['active_recovery'], 'b' * 64)
            self.assertEqual(options['recovery_api'], 1)
            self.prepare_recovery.assert_called_once()
            self.commit_recovery.assert_not_called()
            return {'state': 'completed'}
        self.apply.side_effect = apply
        self.assertEqual(self.run_update(), {'state': 'completed'})
        self.assertFalse(self.open)
        self.assertEqual(self.prepare_recovery.call_args.kwargs['job_owner'], 'a' * 32)
        self.assertEqual(self.prepare_recovery.call_args.kwargs['recovery_api'], 1)
        self.commit_recovery.assert_called_once_with('c' * 64, state=self.state,
            host_root=self.root, job_owner='a' * 32)
        self.assertEqual(self.progress, ['verifying-release', 'preparing-recovery', 'activating', 'committing-recovery'])

    def test_changed_confirmed_manifest_fails_before_signature_or_boot_changes(self):
        (self.prepared / 'manifest.json').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'changed after user confirmation'):
            self.run_update()
        self.verify.assert_not_called()
        self.prepare_recovery.assert_not_called()

    def test_untrusted_key_permissions_prevent_bootstrap_changes(self):
        (self.root / 'etc/elderbrain/release-public.pem').chmod(0o666)
        with self.assertRaisesRegex(ValueError, 'not installer-owned'):
            self.run_update()
        self.prepare_recovery.assert_not_called()

    def test_missing_prepared_release_downloads_under_owned_admission_then_reverifies(self):
        import shutil
        shutil.rmtree(self.prepared)
        @contextmanager
        def admission(*args, **options):
            self.assertEqual(options['owner'], 'a' * 32)
            yield
        def download(*args, **options):
            self.prepared.mkdir(mode=0o700)
            (self.prepared / 'manifest.json').write_bytes(b'manifest')
            (self.prepared / 'manifest.sig').write_bytes(b'signature')
            self.assertEqual(args[0], self.request)
        with patch('update_job.update_admission', side_effect=admission), \
                patch('update_job.download_prepare', side_effect=download) as prepare:
            self.run_update()
        prepare.assert_called_once()
        self.verify.assert_called_once()
        self.apply.assert_called_once()

    def test_candidate_recovery_is_not_selected_before_activation_commits(self):
        self.apply.side_effect = RuntimeError('health failed and rollback completed')
        with self.assertRaisesRegex(RuntimeError, 'health failed'):
            self.run_update()
        self.prepare_recovery.assert_called_once()
        self.commit_recovery.assert_not_called()
        self.assertEqual(self.progress, ['verifying-release', 'preparing-recovery', 'activating'])

    def test_noncommitted_activation_result_never_selects_candidate(self):
        self.apply.return_value = {'state': 'rolled-back'}
        with self.assertRaisesRegex(RuntimeError, 'did not commit'):
            self.run_update()
        self.commit_recovery.assert_not_called()


if __name__ == '__main__':
    unittest.main()
