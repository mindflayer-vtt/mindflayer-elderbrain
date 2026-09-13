"""Check the shipped host generator and its shared, fixed-size vocabulary."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "bootstrap_generator", ROOT / "provisioning/generate-admin-password.py")
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


class BootstrapPasswordTests(unittest.TestCase):
    def test_format_entropy_and_independent_generation(self):
        vocabulary = ROOT / "setup/shared/bootstrap-words.json"
        words = json.loads(vocabulary.read_text())
        self.assertEqual(len(words), 256)
        self.assertEqual(len(set(words)), 256)
        samples = [generator.generate(vocabulary) for _ in range(100)]
        self.assertEqual(len(set(samples)), 100)
        for sample in samples:
            self.assertEqual(len(sample.split("-")), 4)
            self.assertTrue(all(word in words for word in sample.split("-")))
            self.assertTrue(15 <= len(sample) <= 35)

    def test_invalid_word_list_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            vocabulary = Path(directory) / "words.json"
            vocabulary.write_text(json.dumps(["apple"] * 256))
            with self.assertRaises(ValueError):
                generator.generate(vocabulary)

    def test_all_host_generation_paths_use_shared_generator(self):
        for source in ("provisioning/prepare-admin", "appliance/bin/elderbrain"):
            script = (ROOT / source).read_text()
            self.assertIn("generate-admin-password.py", script)
            self.assertNotIn("openssl rand -base64 24", script)
        installer = (ROOT / "provisioning/install.sh").read_text()
        self.assertIn('"$RUNTIME/generate-admin-password.py"', installer)
        self.assertIn('"$RUNTIME/bootstrap-words.json"', installer)
