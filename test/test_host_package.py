import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import test.test_appliance_release as release_fixture
from release_staging import stage

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_host', ROOT / 'release/build-host.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class HostPackageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        (self.source / 'tool.py').write_text('print("fixture")\n')
        (self.source / 'secret').write_text('must-not-ship')
        self.mapping = self.root / 'files.json'
        self.mapping.write_text(json.dumps([{'source': 'tool.py', 'path': 'runtime/tool.py', 'mode': 0o644}]))

    def build(self, name='one'):
        directory = self.root / name
        directory.mkdir(exist_ok=True)
        target = directory / 'elderbrain-host.tar.zst'
        return target, builder.build(self.source, self.mapping, target, '1.1.0')

    def test_reproducible_and_exclusive_publication(self):
        first, metadata = self.build()
        (self.source / 'tool.py').chmod(0o777)
        second, other = self.build('two')
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertEqual(metadata, other)
        with self.assertRaises(FileExistsError):
            self.build()
        self.assertEqual(hashlib.sha256(first.read_bytes()).hexdigest(), metadata['sha256'])

    def test_symlink_source_and_inventory_collision_rejected(self):
        (self.source / 'tool.py').unlink()
        (self.source / 'tool.py').symlink_to(self.source / 'secret')
        with self.assertRaises(ValueError):
            self.build()
        self.mapping.write_text(json.dumps([{'source': 'secret', 'path': 'runtime/VERSION', 'mode': 0o644}]))
        with self.assertRaises(ValueError):
            builder.entries(self.mapping)

    def test_reviewed_inventory_excludes_private_config_and_live_settings(self):
        entries = builder.entries(ROOT / 'release/host-files.json')
        self.assertGreater(len(entries), 70)
        for entry in entries:
            self.assertTrue((ROOT / entry['source']).is_file())
            self.assertNotIn('/private/', entry['source'])
            self.assertNotIn('node_modules', entry['source'])
            self.assertNotIn(entry['path'], ('runtime/appliance.env', 'runtime/sway.conf'))
            self.assertNotIn('signing-public', entry['source'])

    def test_full_reviewed_package_roundtrips_through_signature_and_staging(self):
        release_fixture.ApplianceReleaseTests.setUpClass()
        self.addCleanup(release_fixture.ApplianceReleaseTests.doClassCleanups)
        fixture = release_fixture.ApplianceReleaseTests()
        fixture.setUp()
        target = self.root / 'elderbrain-host.tar.zst'
        metadata = builder.build(ROOT, ROOT / 'release/host-files.json', target, '1.1.0')
        fixture.value['host']['artifact'] = metadata
        raw = json.dumps(fixture.value).encode()
        signature = fixture.sign(raw)
        paths = {entry['path']: entry['mode'] for entry in builder.entries(ROOT / 'release/host-files.json')}
        paths['runtime/VERSION'] = 0o644
        with stage(target, raw, signature, fixture.public.read_bytes(), paths, parent=self.root) as (_, tree):
            self.assertEqual((tree / 'runtime/VERSION').read_text(), '1.1.0\n')
            self.assertEqual((tree / 'runtime/network_checkpoint_restore.py').read_bytes(),
                             (ROOT / 'appliance/lib/network_checkpoint_restore.py').read_bytes())
            self.assertFalse((tree / 'runtime/appliance.env').exists())
            self.assertTrue((tree / 'templates/appliance.env').is_file())


if __name__ == '__main__':
    unittest.main()
