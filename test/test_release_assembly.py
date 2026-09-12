import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

import test.test_appliance_release as release_fixture
from appliance_release import verify, verify_host

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('assemble_release', ROOT / 'release/assemble.py')
assembler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assembler)


class ReleaseAssemblyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        release_fixture.ApplianceReleaseTests.setUpClass()
        cls.addClassCleanup(release_fixture.ApplianceReleaseTests.doClassCleanups)

    def setUp(self):
        self.fixture = release_fixture.ApplianceReleaseTests()
        self.fixture.setUp()
        self.metadata = self.fixture.value
        del self.metadata['host']['artifact']
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def assemble(self, name='release', public=None):
        return assembler.assemble(self.metadata, ROOT, ROOT / 'release/host-files.json',
                                  self.root / name, self.fixture.private, public or self.fixture.public)

    def test_real_release_assembly_verifies_and_is_reproducible(self):
        released = self.assemble()
        directory = self.root / 'release'
        self.assertEqual({file.name for file in directory.iterdir()},
                         {'elderbrain-host.tar.zst', 'manifest.json', 'manifest.sig'})
        checked = verify((directory / 'manifest.json').read_bytes(), (directory / 'manifest.sig').read_bytes(),
                         self.fixture.public.read_bytes())
        self.assertEqual(checked, released)
        verify_host(directory / 'elderbrain-host.tar.zst', checked)
        self.assertNotIn(self.fixture.private.read_text(), (directory / 'manifest.json').read_text())
        self.assemble('second')
        for file in directory.iterdir():
            self.assertEqual(file.read_bytes(), (self.root / 'second' / file.name).read_bytes())
        self.assertNotIn('artifact', self.metadata['host'])

    def test_wrong_independent_pin_never_publishes_manifest(self):
        private = self.root / 'other-private.pem'
        public = self.root / 'other-public.pem'
        subprocess.run(['openssl', 'genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:2048',
                        '-out', str(private)], check=True, capture_output=True)
        subprocess.run(['openssl', 'pkey', '-in', str(private), '-pubout', '-out', str(public)],
                       check=True, capture_output=True)
        with self.assertRaisesRegex(ValueError, 'signature'):
            self.assemble(public=public)
        self.assertEqual(list((self.root / 'release').iterdir()), [])

    def test_existing_output_preserved(self):
        output = self.root / 'release'
        output.mkdir()
        sentinel = output / 'keep'
        sentinel.write_text('existing output')
        with self.assertRaises(FileExistsError):
            self.assemble()
        self.assertEqual(sentinel.read_text(), 'existing output')

    def test_unpinned_image_and_caller_artifact_override_rejected(self):
        self.metadata['host']['artifact'] = {'file': 'untrusted'}
        with self.assertRaises(ValueError):
            self.assemble()
        del self.metadata['host']['artifact']
        self.metadata['setup']['image'] = 'setup:latest'
        with self.assertRaises(ValueError):
            self.assemble()
        self.assertFalse((self.root / 'release').exists())

    def test_publicly_readable_private_key_is_rejected(self):
        self.fixture.private.chmod(0o644)
        self.addCleanup(self.fixture.private.chmod, 0o600)
        with self.assertRaisesRegex(ValueError, 'Signing key'):
            self.assemble()
        self.assertFalse((self.root / 'release').exists())


if __name__ == '__main__':
    unittest.main()
