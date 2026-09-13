from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from . import test_appliance_release as release_fixture

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prepared = load('prepared_inputs_test', ROOT / 'release/prepared-inputs.py')
signer = load('sign_prepared_test', ROOT / 'release/sign-prepared.py')
final_verifier = load('verify_artifacts_test', ROOT / 'release/verify-artifacts.py')


class PreparedReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        release_fixture.ApplianceReleaseTests.setUpClass()
        cls.addClassCleanup(release_fixture.ApplianceReleaseTests.doClassCleanups)

    def setUp(self):
        self.keys = release_fixture.ApplianceReleaseTests()
        self.keys.setUp()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.dependencies = self.root / 'dependencies'
        files = {}
        for name in ('wheels/example-1.0-py3-none-any.whl',
                     'node/playwright-core-1.63.0.tgz'):
            path = self.dependencies / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'prepared-release-fixture')
            files[name] = {'size': path.stat().st_size,
                           'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        inputs = prepared.dependency_input_hashes(ROOT)
        receipt = {
            'format': 1,
            'platform': {'os': 'ubuntu', 'release': '26.04', 'architecture': 'amd64'},
            'python': '3.14.4',
            'requirements': {'example': '1.0'},
            'files': files,
            'inputs': inputs,
            'offlineInstallVerified': False,
        }
        (self.dependencies / 'dependencies.json').write_text(json.dumps(receipt))
        self.notes = self.root / 'notes.md'
        self.notes.write_text('Prepared release test.\n')
        self.commit, self.tree = 'a' * 40, 'b' * 40
        self.version, self.sequence = '0.1.1', 2
        self.setup_image = 'ghcr.io/mindflayer-vtt/setup:0.1.1@sha256:' + 'c' * 64
        self.inputs = self.root / 'prepared'
        prepared.create(ROOT, self.dependencies, self.notes, self.inputs,
                        self.version, self.sequence, self.setup_image,
                        self.commit, self.tree)

    def verify(self, directory=None):
        return prepared.verify(directory or self.inputs, ROOT, self.commit, self.tree,
                               self.version, self.sequence)

    def rewrite_receipt(self, value):
        (self.inputs / prepared.RECEIPT).write_bytes(prepared.canonical(value) + b'\n')

    def test_fixed_receipt_revalidates_metadata_source_and_every_artifact(self):
        receipt, metadata = self.verify()
        self.assertEqual(receipt['sourceCommit'], self.commit)
        self.assertEqual(receipt['sourceTree'], self.tree)
        self.assertEqual(receipt['version'], self.version)
        self.assertEqual(receipt['releaseSequence'], self.sequence)
        self.assertEqual(set(receipt['preparedFiles']), set(prepared.FILES))
        self.assertEqual(metadata['host']['artifact']['sha256'],
                         receipt['preparedFiles']['elderbrain-host.tar.zst']['sha256'])
        self.assertEqual(metadata['dependencies']['artifact']['sha256'],
                         receipt['preparedFiles']['elderbrain-dependencies.tar.zst']['sha256'])

    def test_transfer_rejects_changed_bytes_extra_entries_and_symlinks(self):
        original = (self.inputs / 'release-notes.md').read_bytes()
        (self.inputs / 'release-notes.md').write_bytes(b'changed\n')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            self.verify()
        (self.inputs / 'release-notes.md').write_bytes(original)
        (self.inputs / 'extra').write_text('unexpected')
        with self.assertRaisesRegex(ValueError, 'unexpected'):
            self.verify()
        (self.inputs / 'extra').unlink()
        (self.inputs / 'release-notes.md').unlink()
        (self.inputs / 'release-notes.md').symlink_to(self.notes)
        with self.assertRaisesRegex(ValueError, 'Invalid prepared input'):
            self.verify()

    def test_receipt_rejects_duplicate_unknown_and_wrong_workflow_identity(self):
        path = self.inputs / prepared.RECEIPT
        original = path.read_bytes()
        path.write_bytes(original.replace(b'{', b'{"format":1,', 1))
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            self.verify()
        path.write_bytes(original)
        value = json.loads(original)
        value['unknown'] = True
        self.rewrite_receipt(value)
        with self.assertRaises(ValueError):
            self.verify()
        value.pop('unknown')
        value['format'] = True
        self.rewrite_receipt(value)
        with self.assertRaisesRegex(ValueError, 'format'):
            self.verify()
        path.write_bytes(original)
        with self.assertRaisesRegex(ValueError, 'identity'):
            prepared.verify(self.inputs, ROOT, 'd' * 40, self.tree,
                            self.version, self.sequence)

    def test_metadata_is_reparsed_strictly_even_if_receipt_hashes_are_rewritten(self):
        metadata_path = self.inputs / 'release-metadata.json'
        metadata_path.write_bytes(metadata_path.read_bytes().replace(
            b'{', b'{"format":2,', 1))
        receipt = json.loads((self.inputs / prepared.RECEIPT).read_text())
        data = metadata_path.read_bytes()
        receipt['metadataSha256'] = hashlib.sha256(data).hexdigest()
        receipt['preparedFiles']['release-metadata.json'] = {
            'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        self.rewrite_receipt(receipt)
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            self.verify()

    def test_prebuilt_inputs_are_signed_and_then_verified_without_the_key(self):
        output = self.root / 'release'
        result = signer.sign(self.inputs, output, self.keys.private, self.keys.public,
                             ROOT, self.commit, self.tree, self.version, self.sequence)
        self.assertEqual(result['releaseSequence'], 2)
        checked = final_verifier.check(output, self.keys.public, ROOT)
        self.assertEqual(checked, result)
        self.assertEqual({entry.name for entry in output.iterdir()}, {
            'elderbrain-host.tar.zst', 'elderbrain-dependencies.tar.zst',
            'manifest.json', 'manifest.sig'})


if __name__ == '__main__':
    unittest.main()
