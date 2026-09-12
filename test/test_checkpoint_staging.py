import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'appliance/lib'))
from checkpoint_staging import stage, read_json, DEFAULT_CONFIG


class StagingTests(unittest.TestCase):
    def test_preferences_are_private_and_do_not_change_live_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current, checkpoint = root / 'current', root / 'checkpoint'
            for base in (current, checkpoint):
                (base / 'elderbrain').mkdir(parents=True)
            live = current / 'elderbrain/config.json'
            live.write_text(json.dumps({**DEFAULT_CONFIG, 'configured': True, 'controllers': {'one': {'name': 'keep'}}}))
            (checkpoint / 'elderbrain/config.json').write_text(json.dumps({**DEFAULT_CONFIG, 'domain': 'old.local'}))
            before = live.read_bytes()
            sources, targets = stage(current, checkpoint, root / 'staged', ['preferences'])
            self.assertEqual(live.read_bytes(), before)
            value = json.loads(sources['preferences'].read_text())
            self.assertEqual(value['domain'], 'old.local')
            self.assertTrue(value['configured'])
            self.assertEqual(value['controllers'], {'one': {'name': 'keep'}})
            self.assertEqual(targets['preferences'], live)
            self.assertEqual(sources['preferences'].stat().st_mode & 0o777, 0o600)

    def test_json_parent_symlink_and_oversized_files_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'real').mkdir()
            (root / 'real/config.json').write_text('{}')
            (root / 'link').symlink_to(root / 'real')
            with self.assertRaises(OSError):
                read_json(root, 'link/config.json', fallback={})
            with self.assertRaises(ValueError):
                read_json(root, 'real/config.json', fallback={}, limit=1)

    def test_foundry_stages_whole_instance_and_rejects_external_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'checkpoint/foundry/worlds').mkdir(parents=True)
            (root / 'checkpoint/foundry/worlds/world').write_text('world-data')
            sources, targets = stage(root / 'current', root / 'checkpoint', root / 'staged', ['foundry'])
            self.assertEqual(set(sources), {'foundry'})
            self.assertEqual((sources['foundry'] / 'worlds/world').read_text(), 'world-data')
            self.assertEqual(targets['foundry'], root / 'current/foundry')
            (root / 'checkpoint/foundry/escape').symlink_to('/etc')
            with self.assertRaises(ValueError):
                stage(root / 'current', root / 'checkpoint', root / 'rejected', ['foundry'])
