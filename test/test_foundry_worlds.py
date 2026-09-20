import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'appliance/lib'))
spec = importlib.util.spec_from_file_location('host_jobs', ROOT / 'appliance/lib/host_jobs.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FoundryWorldTests(unittest.TestCase):
    def test_catalogue_returns_bounded_world_titles_and_ids(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for identifier, title in [('zeta-world', 'Zeta'), ('ardin-3', 'Ardin')]:
                directory = root / identifier
                directory.mkdir()
                (directory / 'world.json').write_text(json.dumps({'id': identifier, 'title': title}))
            self.assertEqual(module.foundry_worlds(root), [
                {'id': 'ardin-3', 'title': 'Ardin'},
                {'id': 'zeta-world', 'title': 'Zeta'},
            ])

    def test_catalogue_ignores_unsafe_or_ambiguous_entries(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mismatch = root / 'expected'
            mismatch.mkdir()
            (mismatch / 'world.json').write_text(json.dumps({'id': 'different', 'title': 'Wrong'}))
            malformed = root / 'malformed'
            malformed.mkdir()
            (malformed / 'world.json').write_text('{')
            (root / 'linked').symlink_to(mismatch, target_is_directory=True)
            self.assertEqual(module.foundry_worlds(root), [])

    def test_installation_wires_catalogue_into_runtime(self):
        jobs = (ROOT / 'appliance/lib/host_jobs.py').read_text()
        self.assertIn('def foundry_worlds(', jobs)
        server = (ROOT / 'appliance/lib/management-server').read_text()
        self.assertIn('action == "foundry-worlds"', server)


if __name__ == '__main__':
    unittest.main()
