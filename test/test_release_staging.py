from contextlib import contextmanager
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from . import test_appliance_release as release_fixture
from release_staging import stage, inventory


class ReleaseStagingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Reuse real signature fixtures without inheriting their test methods.
        release_fixture.ApplianceReleaseTests.setUpClass()
        cls.addClassCleanup(release_fixture.ApplianceReleaseTests.doClassCleanups)

    def setUp(self):
        self.fixture = release_fixture.ApplianceReleaseTests()
        self.fixture.setUp()
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.parent = self.root / 'staging'
        self.parent.mkdir(mode=0o700)
        self.paths = {'runtime/example.py': 0o644, 'bin/elderbrain': 0o755}

    def package(self, extras=(), omit=None):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w', format=tarfile.USTAR_FORMAT) as archive:
            for name in self.paths:
                if name == omit:
                    continue
                member = tarfile.TarInfo(name)
                member.size = 7
                member.mode = 0o777  # Modes are normalized from trusted policy.
                archive.addfile(member, io.BytesIO(b'fixture'))
            for member, data in extras:
                archive.addfile(member, io.BytesIO(data))
        compressed = subprocess.run(['zstd', '-q', '-c'], input=stream.getvalue(), capture_output=True, check=True).stdout
        self.archive = self.root / 'host.tar.zst'
        self.archive.write_bytes(compressed)
        value = self.fixture.value
        value['host']['artifact'].update(size=len(compressed), sha256=hashlib.sha256(compressed).hexdigest())
        self.manifest = json.dumps(value).encode()
        self.signature = self.fixture.sign(self.manifest)

    @contextmanager
    def staged(self):
        with stage(self.archive, self.manifest, self.signature, self.fixture.public.read_bytes(),
                   self.paths, parent=self.parent) as result:
            yield result

    def test_real_signed_zstd_package_stages_privately_and_cleans_up(self):
        self.package()
        with self.staged() as (release, tree):
            self.assertEqual(release['version'], '1.2.3')
            for name, mode in self.paths.items():
                self.assertEqual((tree / name).read_bytes(), b'fixture')
                self.assertEqual((tree / name).stat().st_mode & 0o777, mode)
            self.assertEqual(tree.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(list(self.parent.iterdir()), [])

    def test_missing_duplicate_and_traversal_members_rejected(self):
        self.package(omit='bin/elderbrain')
        with self.assertRaises(ValueError), self.staged():
            pass
        for name in ('runtime/example.py', '../../outside', '/etc/passwd'):
            member = tarfile.TarInfo(name)
            self.package([(member, b'')])
            with self.assertRaises(ValueError), self.staged():
                pass
            self.assertEqual(list(self.parent.iterdir()), [])

    def test_links_devices_and_privileged_modes_rejected(self):
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE):
            member = tarfile.TarInfo('bin/elderbrain')
            member.type = kind
            member.linkname = '/etc/passwd'
            self.package([(member, b'')], omit='bin/elderbrain')
            with self.assertRaises(ValueError), self.staged():
                pass
        member = tarfile.TarInfo('bin/elderbrain')
        member.mode = 0o4755
        self.package([(member, b'')], omit='bin/elderbrain')
        with self.assertRaises(ValueError), self.staged():
            pass

    def test_hash_failure_precedes_decompression(self):
        self.package()
        self.archive.write_bytes(b'x' * self.archive.stat().st_size)
        import release_staging
        real_run = subprocess.run
        calls = []
        def run(args, **kwargs):
            calls.append(args[0])
            return real_run(args, **kwargs)
        with patch.object(release_staging.subprocess, 'run', side_effect=run):
            with self.assertRaises(ValueError), self.staged():
                pass
        self.assertEqual(calls, ['openssl'])

    def test_unpacked_file_bound_and_private_parent_required(self):
        self.package()
        with patch('release_staging.FILE_LIMIT', 6):
            with self.assertRaises(ValueError), self.staged():
                pass
        self.parent.chmod(0o755)
        with self.assertRaises(ValueError), self.staged():
            pass

    def test_trusted_inventory_rejects_path_and_prefix_collisions(self):
        for paths in ({'../live': 0o644}, {'runtime': 0o644, 'runtime/file': 0o644},
                      {'runtime/file': 0o4755}, {'runtime//file': 0o644}):
            with self.assertRaises(ValueError):
                inventory(paths)

    def test_kernel_decompression_limit_fails_and_cleans_private_tree(self):
        self.package()
        with patch('release_staging.EXPANDED_LIMIT', 512):
            with self.assertRaises(subprocess.CalledProcessError), self.staged():
                pass
        self.assertEqual(list(self.parent.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
