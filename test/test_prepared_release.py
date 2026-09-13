import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
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
approver = load('verify_prepared_release_test', ROOT / 'release/verify-prepared-release.py')
signer = load('sign_manifest_test', ROOT / 'release/sign-manifest.py')
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

    def rehash_host_and_metadata(self, artifact):
        metadata_path = self.inputs / 'release-metadata.json'
        metadata = json.loads(metadata_path.read_text())
        metadata['host']['artifact'] = artifact
        metadata_bytes = prepared.canonical(metadata) + b'\n'
        metadata_path.write_bytes(metadata_bytes)
        receipt = json.loads((self.inputs / prepared.RECEIPT).read_text())
        host_path = self.inputs / 'elderbrain-host.tar.zst'
        receipt['preparedFiles']['elderbrain-host.tar.zst'] = {
            'size': host_path.stat().st_size, 'sha256': prepared.hash_file(host_path)}
        receipt['metadataSha256'] = hashlib.sha256(metadata_bytes).hexdigest()
        receipt['preparedFiles']['release-metadata.json'] = {
            'size': len(metadata_bytes), 'sha256': hashlib.sha256(metadata_bytes).hexdigest()}
        self.rewrite_receipt(receipt)

    def rewrite_host_archive(self, transform):
        archive = self.inputs / 'elderbrain-host.tar.zst'
        raw = self.root / 'host-input.tar'
        with raw.open('wb') as output:
            subprocess.run(['zstd', '-q', '-d', '-c', str(archive)], check=True,
                           stdout=output, stdin=subprocess.DEVNULL)
        members = []
        with tarfile.open(raw, 'r:') as package:
            for member in package:
                members.append((member.name, package.extractfile(member).read(), member.mode))
        members = transform(members)
        rewritten = self.root / 'host-rewritten.tar'
        with tarfile.open(rewritten, 'w', format=tarfile.USTAR_FORMAT) as package:
            for name, data, mode in members:
                member = tarfile.TarInfo(name)
                member.size, member.mode = len(data), mode
                member.uid = member.gid = member.mtime = 0
                package.addfile(member, io.BytesIO(data))
        archive.unlink()
        with archive.open('wb') as output:
            subprocess.run(['zstd', '-q', '-T1', '-19', '-c', str(rewritten)], check=True,
                           stdout=output, stdin=subprocess.DEVNULL)
        artifact = {'file': archive.name, 'size': archive.stat().st_size,
                    'sha256': prepared.hash_file(archive)}
        self.rehash_host_and_metadata(artifact)

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

    def test_prebuilt_inputs_are_approved_signed_and_then_verified_without_the_key(self):
        output = self.root / 'release'
        result = approver.approve(self.inputs, output, ROOT, self.commit, self.tree,
                                  self.version, self.sequence)
        signed = signer.sign(output / 'manifest.json', output / 'manifest.sig',
                             self.keys.private, self.keys.public)
        self.assertEqual(signed, result)
        self.assertEqual(result['releaseSequence'], 2)
        checked = final_verifier.check(output, self.keys.public, ROOT)
        self.assertEqual(checked, result)
        self.assertEqual({entry.name for entry in output.iterdir()}, {
            'elderbrain-host.tar.zst', 'elderbrain-dependencies.tar.zst',
            'manifest.json', 'manifest.sig'})

    def test_fully_rehashed_modified_host_is_rejected_against_clean_checkout(self):
        altered = self.root / 'altered-source'
        entries = approver.host.entries(ROOT / 'release/host-files.json')
        for entry in entries:
            destination = altered / entry['source']
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / entry['source'], destination)
        victim = entries[0]['source']
        with (altered / victim).open('ab') as stream:
            stream.write(b'\nmalicious preparation mutation\n')
        archive = self.inputs / 'elderbrain-host.tar.zst'
        archive.unlink()
        artifact = approver.host.build(
            altered, ROOT / 'release/host-files.json', archive, self.version)
        self.rehash_host_and_metadata(artifact)

        # All prepare-controlled hashes and source identity claims are consistent.
        prepared.verify(self.inputs, ROOT, self.commit, self.tree,
                        self.version, self.sequence)
        with self.assertRaisesRegex(ValueError, 'differs from clean checkout'):
            approver.approve(self.inputs, self.root / 'rejected', ROOT, self.commit,
                             self.tree, self.version, self.sequence)

    def test_deep_approval_rejects_missing_extra_mode_and_wrong_version(self):
        original = {
            name: (self.inputs / name).read_bytes()
            for name in ('elderbrain-host.tar.zst', 'release-metadata.json', prepared.RECEIPT)
        }
        cases = (
            ('missing', lambda members: members[:-1], 'inventory'),
            ('extra', lambda members: members + [('unexpected', b'x', 0o644)], 'unsafe'),
            ('mode', lambda members: [(name, data, 0o755 if mode == 0o644 else 0o644)
                                      if index == 1 else (name, data, mode)
                                      for index, (name, data, mode) in enumerate(members)], 'unsafe'),
            ('version', lambda members: [(name, b'9.9.9\n', mode)
                                         if name == 'runtime/VERSION' else (name, data, mode)
                                         for name, data, mode in members], 'VERSION'),
        )
        for label, transform, message in cases:
            with self.subTest(case=label):
                for name, content in original.items():
                    (self.inputs / name).write_bytes(content)
                self.rewrite_host_archive(transform)
                prepared.verify(self.inputs, ROOT, self.commit, self.tree,
                                self.version, self.sequence)
                with self.assertRaisesRegex(ValueError, message):
                    approver.approve(self.inputs, self.root / ('reject-' + label), ROOT,
                                     self.commit, self.tree, self.version, self.sequence)

    def test_clean_checkout_source_symlink_is_rejected(self):
        source = self.root / 'source'
        source.mkdir()
        outside = self.root / 'outside'
        outside.write_bytes(b'expected')
        (source / 'linked').symlink_to(outside)
        inventory = self.root / 'inventory.json'
        inventory.write_text(json.dumps([
            {'source': 'linked', 'path': 'runtime/linked', 'mode': 0o644}]))
        tree = self.root / 'tree'
        (tree / 'runtime').mkdir(parents=True)
        (tree / 'runtime/VERSION').write_text(self.version + '\n')
        (tree / 'runtime/linked').write_bytes(b'expected')
        with self.assertRaisesRegex(ValueError, 'symlink'):
            approver.compare_host_tree(tree, source, inventory, self.version)


if __name__ == '__main__':
    unittest.main()
