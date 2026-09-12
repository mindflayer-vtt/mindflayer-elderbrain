import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PreserveBaselineTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / 'test/.qemu'
        parent.mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(prefix='baseline-helper-', dir=parent)
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.run = self.root / 'evidence'
        self.run.mkdir()
        self.baseline = self.run / 'baseline.json'
        self.baseline.write_text('{}\n')
        digest = hashlib.sha256(self.baseline.read_bytes()).hexdigest()
        (self.run / 'baseline.sha256').write_text(f'{digest}  baseline.json\n')
        (self.run / 'known_hosts').write_text('saved-test-identity\n')
        self.key = self.root / 'key'
        self.key.touch()
        self.calls = self.root / 'calls'
        binary = self.root / 'ssh'
        binary.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$TEST_SSH_CALLS"\nexit 71\n')
        binary.chmod(0o700)

    def verify(self):
        return subprocess.run(
            ['bash', str(ROOT / 'test/qemu/preserve-baseline.sh'), 'verify', str(self.run)],
            env={**os.environ, 'PATH': f'{self.root}:{os.environ["PATH"]}',
                 'QEMU_SSH_PRIVATE_KEY': str(self.key), 'TEST_SSH_CALLS': str(self.calls)},
            capture_output=True, text=True, timeout=10,
        )

    def test_verify_requires_saved_identity_before_contact(self):
        (self.run / 'known_hosts').unlink()
        result = self.verify()
        self.assertEqual(result.returncode, 2)
        self.assertIn('Saved SSH identity not found', result.stderr)
        self.assertFalse(self.calls.exists())

    def test_empty_or_linked_identity_rejected(self):
        trust = self.run / 'known_hosts'
        trust.write_text('')
        self.assertEqual(self.verify().returncode, 2)
        trust.unlink()
        trust.symlink_to(self.baseline)
        self.assertEqual(self.verify().returncode, 2)
        self.assertFalse(self.calls.exists())

    def test_corrupt_baseline_rejected_before_contact(self):
        self.baseline.write_text('changed\n')
        self.assertNotEqual(self.verify().returncode, 0)
        self.assertFalse(self.calls.exists())

    def test_missing_checksum_rejected_before_contact(self):
        (self.run / 'baseline.sha256').unlink()
        self.assertNotEqual(self.verify().returncode, 0)
        self.assertFalse(self.calls.exists())

    def test_verify_uses_strict_saved_trust(self):
        self.assertEqual(self.verify().returncode, 71)
        args = self.calls.read_text().splitlines()
        self.assertIn('StrictHostKeyChecking=yes', args)
        self.assertIn('GlobalKnownHostsFile=/dev/null', args)
        self.assertIn(f'UserKnownHostsFile={self.run}/known_hosts', args)
        self.assertNotIn('StrictHostKeyChecking=accept-new', args)


if __name__ == '__main__':
    unittest.main()
