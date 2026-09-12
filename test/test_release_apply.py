from contextlib import contextmanager
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from release_apply import activate


class ApplyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.prepared = self.root / 'prepared'
        self.prepared.mkdir(mode=0o700)
        (self.prepared / 'manifest.json').write_bytes(b'signed manifest')
        (self.prepared / 'manifest.sig').write_bytes(b'signature')
        self.guard = self.enterContext(patch('release_apply.persistent_identity', return_value='fixture'))
        self.proof = self.enterContext(patch('release_apply.verify_active'))
        self.policy = self.enterContext(patch('release_apply.ReleasePolicy')).return_value
        self.services = self.enterContext(patch('release_apply.UpdateServices')).return_value
        self.maintenance = self.enterContext(patch('release_apply.Maintenance'))
        self.checkpoints = self.enterContext(patch('release_apply.UpdateCheckpoints')).return_value
        self.source_map = self.enterContext(patch('release_apply.sources', return_value={'fixed': 'source'}))
        self.target_map = self.enterContext(patch('release_apply.targets', return_value={'fixed': 'target'}))
        self.coordinator = self.enterContext(patch('release_apply.Activation'))
        self.open = False
        self.release = {'version': '1.0.1'}
        @contextmanager
        def candidate(*args, **kwargs):
            self.open = True
            try:
                yield self.release, self.root / 'authenticated'
            finally:
                self.open = False
        self.candidate = self.enterContext(patch('release_apply.candidate', side_effect=candidate))
        def apply(manifest, signature, key, prepare_sources):
            self.assertEqual((manifest, signature, key), (b'signed manifest', b'signature', b'pinned key'))
            self.assertEqual(prepare_sources({'version': '1.0.1'}), {'fixed': 'source'})
            self.assertTrue(self.open, 'Candidate must survive transaction preparation and activation')
            return {'id': 'a' * 32, 'version': '1.0.1', 'state': 'completed', 'private': 'omit'}
        self.coordinator.return_value.activate.side_effect = apply

    def activate(self):
        return activate(self.prepared, b'pinned key', {'trusted': 0o644},
            dependency_directory=self.root / 'dependencies', bootstrap_tree=self.root / 'bootstrap',
            platform={'architecture': 'amd64'}, configuration_schema=1, parent=self.root, host_root=self.root,
            active_recovery='b' * 64, candidate_bootstrap='c' * 64, recovery_api=1)

    def test_wires_fixed_coordinator_and_retains_candidate_until_activation_finishes(self):
        self.assertEqual(self.activate(), {'id': 'a' * 32, 'version': '1.0.1', 'state': 'completed'})
        self.assertFalse(self.open)
        self.proof.assert_called_once()
        self.proof.assert_called_once_with('b' * 64, 1, host_root=self.root)
        self.policy.require_new.assert_called_once_with({'version': '1.0.1'})
        self.services.validate.assert_called_once()
        options = self.coordinator.call_args.kwargs
        self.assertIs(options['checkpoint'], self.checkpoints.checkpoint)
        self.assertIs(options['restore_checkpoint'], self.checkpoints.restore)
        self.assertIs(options['release_checkpoint'], self.checkpoints.release)
        self.assertIs(options['refresh'], self.checkpoints.guard)
        self.assertIs(options['commit_release'], self.policy.commit)
        self.assertTrue(callable(options['before_switch']))
        self.assertEqual(options['candidate_bootstrap'], 'c' * 64)

    def test_missing_storage_prevents_maintenance_creation(self):
        self.guard.return_value = None
        with self.assertRaisesRegex(ValueError, 'verified persistent storage'):
            self.activate()
        self.maintenance.assert_not_called()

    def test_recovery_or_previous_runtime_failure_prevents_candidate_preparation(self):
        self.proof.side_effect = ValueError('bootstrap missing')
        with self.assertRaisesRegex(ValueError, 'bootstrap missing'):
            self.activate()
        self.candidate.assert_not_called()
        self.proof.side_effect = None
        self.services.validate.side_effect = ValueError('legacy builds')
        with self.assertRaisesRegex(ValueError, 'legacy builds'):
            self.activate()
        self.candidate.assert_not_called()

    def test_sequence_is_rechecked_inside_activation_admission(self):
        self.policy.require_new.side_effect = ValueError('Release sequence is not newer')
        with self.assertRaisesRegex(ValueError, 'not newer'):
            self.activate()
        self.candidate.assert_not_called()
        self.coordinator.return_value.activate.assert_called_once()

    def test_manifest_change_releases_candidate_and_refuses_target_mapping(self):
        self.release = {'version': 'different'}
        with self.assertRaisesRegex(ValueError, 'changed during activation'):
            self.activate()
        self.assertFalse(self.open)
        self.source_map.assert_not_called()


if __name__ == '__main__':
    unittest.main()
