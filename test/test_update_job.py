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
        self.verify = self.enterContext(patch('update_job.verify', return_value={'format': 2, 'version': '1.2.3'}))
        self.enterContext(patch('update_job.require_compatible'))
        self.install = self.enterContext(patch('update_job.install'))
        self.apply = self.enterContext(patch('update_job.activate', return_value={'state': 'completed'}))
        self.enterContext(patch('update_job.subprocess.run'))
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
            return {'state': 'completed'}
        self.apply.side_effect = apply
        self.assertEqual(self.run_update(), {'state': 'completed'})
        self.assertFalse(self.open)
        self.assertEqual(self.install.call_args.kwargs['job_owner'], 'a' * 32)
        self.assertEqual(self.progress, ['verifying-release', 'preparing-recovery', 'activating'])

    def test_changed_confirmed_manifest_fails_before_signature_or_boot_changes(self):
        (self.prepared / 'manifest.json').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'changed after user confirmation'):
            self.run_update()
        self.verify.assert_not_called()
        self.install.assert_not_called()

    def test_untrusted_key_permissions_prevent_bootstrap_changes(self):
        (self.root / 'etc/elderbrain/release-public.pem').chmod(0o666)
        with self.assertRaisesRegex(ValueError, 'not installer-owned'):
            self.run_update()
        self.install.assert_not_called()


if __name__ == '__main__':
    unittest.main()
