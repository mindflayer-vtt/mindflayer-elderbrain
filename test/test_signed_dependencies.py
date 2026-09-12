from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import test.test_release_assembly as assembly_fixture
import test.test_appliance_release as release_fixture
from appliance_release import validate, verify
from release_staging import stage

ROOT = Path(__file__).resolve().parents[1]


class SignedDependencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        release_fixture.ApplianceReleaseTests.setUpClass()
        cls.addClassCleanup(release_fixture.ApplianceReleaseTests.doClassCleanups)

    def setUp(self):
        self.fixture = release_fixture.ApplianceReleaseTests()
        self.fixture.setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.inputs = self.root / 'inputs'
        files = {}
        for name in ('wheels/example-1.0-py3-none-any.whl', 'node/playwright-core-1.63.0.tgz'):
            file = self.inputs / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(b'fixture-bytes-not-installable')
            files[name] = {'size': file.stat().st_size, 'sha256': hashlib.sha256(file.read_bytes()).hexdigest()}
        (self.inputs / 'dependencies.json').write_text(json.dumps({'format': 1, 'platform': self.fixture.value['platform'],
                                                                 'python': '3.14.4', 'files': files}))

    def assemble(self):
        metadata = deepcopy(self.fixture.value)
        metadata['format'] = 2
        del metadata['host']['artifact']
        return assembly_fixture.assembler.assemble(metadata, ROOT, ROOT / 'release/host-files.json',
            self.root / 'release', self.fixture.private, self.fixture.public, dependency_directory=self.inputs)

    def test_complete_signature_chain_stages_exact_dependency_files(self):
        release = self.assemble()
        output = self.root / 'release'
        raw, signature = (output / 'manifest.json').read_bytes(), (output / 'manifest.sig').read_bytes()
        self.assertEqual(verify(raw, signature, self.fixture.public.read_bytes()), release)
        with stage(output / 'elderbrain-dependencies.tar.zst', raw, signature, self.fixture.public.read_bytes(),
                   parent=self.root, component='dependencies') as (_, tree):
            for name in release['dependencies']['files']:
                self.assertEqual((tree / name).read_bytes(), (self.inputs / name).read_bytes())
        self.assertEqual({file.name for file in output.iterdir()},
                         {'manifest.json', 'manifest.sig', 'elderbrain-host.tar.zst', 'elderbrain-dependencies.tar.zst'})

    def test_dependency_tampering_is_rejected_before_staging(self):
        self.assemble()
        output = self.root / 'release'
        archive = output / 'elderbrain-dependencies.tar.zst'
        archive.write_bytes(b'x' * archive.stat().st_size)
        with self.assertRaises(ValueError), stage(archive, (output / 'manifest.json').read_bytes(),
                (output / 'manifest.sig').read_bytes(), self.fixture.public.read_bytes(), parent=self.root, component='dependencies'):
            pass

    def test_long_wheel_filename_roundtrips_with_only_path_metadata(self):
        receipt_file = self.inputs / 'dependencies.json'
        receipt = json.loads(receipt_file.read_text())
        old = 'wheels/example-1.0-py3-none-any.whl'
        name = 'wheels/example-1.0-cp314-cp314-' + 'manylinux_2_17_x86_64.' * 5 + 'whl'
        (self.inputs / old).rename(self.inputs / name)
        receipt['files'][name] = receipt['files'].pop(old)
        receipt_file.write_text(json.dumps(receipt))
        self.assemble()
        output = self.root / 'release'
        with stage(output / 'elderbrain-dependencies.tar.zst', (output / 'manifest.json').read_bytes(),
                   (output / 'manifest.sig').read_bytes(), self.fixture.public.read_bytes(),
                   parent=self.root, component='dependencies') as (_, tree):
            self.assertEqual((tree / name).read_bytes(), (self.inputs / name).read_bytes())

    def test_unsafe_signed_inventory_and_missing_format2_component_rejected(self):
        value = self.assemble()
        changed = deepcopy(value)
        del changed['dependencies']
        with self.assertRaises(ValueError):
            validate(changed)
        for name in ('../../etc/passwd', 'wheels/../../escape.whl', 'runtime/tool.py'):
            changed = deepcopy(value)
            changed['dependencies']['files'][name] = {'size': 1, 'sha256': 'a' * 64}
            with self.assertRaises(ValueError):
                validate(changed)

    def test_build_receipt_does_not_authorize_changed_payload(self):
        (self.inputs / 'node/playwright-core-1.63.0.tgz').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'differ from build receipt'):
            self.assemble()
        self.assertFalse((self.root / 'release/manifest.json').exists())

    def test_format2_cannot_omit_its_dependency_archive(self):
        metadata = deepcopy(self.fixture.value)
        metadata['format'] = 2
        del metadata['host']['artifact']
        with self.assertRaisesRegex(ValueError, 'dependency input directory'):
            assembly_fixture.assembler.assemble(metadata, ROOT, ROOT / 'release/host-files.json',
                self.root / 'release', self.fixture.private, self.fixture.public)

    def test_signed_per_file_hash_is_checked_in_addition_to_archive_hash(self):
        release = self.assemble()
        release['dependencies']['files']['node/playwright-core-1.63.0.tgz']['sha256'] = '0' * 64
        raw = json.dumps(release).encode()
        signature = self.fixture.sign(raw)
        with self.assertRaisesRegex(ValueError, 'signed inventory'), stage(
                self.root / 'release/elderbrain-dependencies.tar.zst', raw, signature,
                self.fixture.public.read_bytes(), parent=self.root, component='dependencies'):
            pass


if __name__ == '__main__':
    unittest.main()
