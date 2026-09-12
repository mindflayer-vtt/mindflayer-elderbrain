import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'appliance/lib'))
from release_policy import ReleasePolicy


class ReleasePolicyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.state = Path(temporary.name)
        self.policy = ReleasePolicy(self.state)
        self.digest = hashlib.sha256(b'signed manifest').hexdigest()

    def release(self, sequence):
        return {'releaseSequence': sequence}

    def record(self, sequence, version='1.2.3', digest=None):
        return {'releaseSequence': sequence, 'version': version,
                'manifestSha256': digest or self.digest}

    def test_successful_commit_is_durable_and_replay_is_rejected(self):
        self.assertEqual(self.policy.current(), {'highestSequence': 0})
        self.policy.require_new(self.release(7))
        accepted = self.policy.commit(self.record(7))
        self.assertEqual(accepted['highestSequence'], 7)
        self.assertEqual((self.state / 'release-policy.json').stat().st_mode & 0o777, 0o600)
        with self.assertRaisesRegex(ValueError, 'not newer'):
            self.policy.require_new(self.release(7))
        with self.assertRaisesRegex(ValueError, 'not newer'):
            self.policy.require_new(self.release(6))

    def test_recovery_commit_is_idempotent_but_identity_conflicts_fail(self):
        expected = self.policy.commit(self.record(9))
        self.assertEqual(self.policy.commit(self.record(9)), expected)
        with self.assertRaisesRegex(ValueError, 'identity conflicts'):
            self.policy.commit(self.record(9, version='1.2.4'))
        with self.assertRaisesRegex(ValueError, 'roll back'):
            self.policy.commit(self.record(8))
        self.assertEqual(self.policy.current(), expected)

    def test_corrupt_or_public_policy_fails_closed(self):
        path = self.state / 'release-policy.json'
        path.write_text(json.dumps({'format': 1, 'highestSequence': 4,
                                    'version': '1.2.3', 'manifestSha256': self.digest}))
        path.chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'private'):
            self.policy.current()
        path.chmod(0o600)
        path.write_text('{"format":1,"format":1}')
        with self.assertRaises(ValueError):
            self.policy.current()

    def test_explicit_install_baseline_can_reset_a_preserved_newer_sequence(self):
        self.policy.commit(self.record(9))
        baseline = self.policy.install_baseline(self.record(2, version='1.0.0'))
        self.assertEqual(baseline['highestSequence'], 2)
        self.assertEqual(self.policy.current(), baseline)
        with self.assertRaisesRegex(ValueError, 'not newer'):
            self.policy.require_new(self.release(2))


if __name__ == '__main__':
    unittest.main()
