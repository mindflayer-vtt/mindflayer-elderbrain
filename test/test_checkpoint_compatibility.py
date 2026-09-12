from copy import deepcopy
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'appliance/lib'))
from checkpoint_compatibility import capture, require_compatible


class CompatibilityTests(unittest.TestCase):
    def test_records_actual_image_identity_and_rejects_changed_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'VERSION').write_text('1.0.0')
            (root / 'compose.yaml').write_text('runtime')
            def run(args, **kwargs):
                if args[1] == 'compose':
                    self.assertIn('-a', args)  # containers are stopped during capture
                    return SimpleNamespace(stdout='a' * 64)
                return SimpleNamespace(stdout='foundry sha256:' + 'b' * 64)
            recorded = capture(root, run=run)
            require_compatible(recorded, recorded, ['foundry'])
            for field, value in [('applianceVersion', '2.0.0'), ('composeSha256', 'c' * 64),
                                 ('images', {'foundry': 'sha256:' + 'c' * 64})]:
                changed = deepcopy(recorded)
                changed[field] = value
                with self.assertRaises(ValueError):
                    require_compatible(recorded, changed, ['foundry'])
            missing = {**recorded, 'images': {}}
            with self.assertRaises(ValueError):
                require_compatible(missing, missing, ['foundry'])
            with self.assertRaises(ValueError):
                require_compatible(None, recorded, ['preferences'])
