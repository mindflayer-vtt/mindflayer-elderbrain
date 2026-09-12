import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_dependencies', ROOT / 'release/build-dependencies.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class DependencyBuilderTests(unittest.TestCase):
    def test_current_dependency_inputs_are_exact_and_browser_integrity_is_pinned(self):
        serial = builder.requirements(ROOT / 'config/defaults/serial-requirements.txt')
        self.assertEqual(serial['esptool'], '4.9.0')
        self.assertEqual(len(serial), 14)
        builder.requirements(ROOT / 'config/defaults/borgmatic-requirements.txt')
        version, digest = builder.browser_package(ROOT / 'provisioning/graphics/package-lock.json')
        self.assertEqual(version, '1.63.0')
        self.assertEqual(len(digest), 64)

    def test_ranges_urls_includes_and_duplicate_normalized_names_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            file = Path(temporary) / 'requirements.txt'
            for value in ('esptool>=4', '-r other.txt', 'https://example.test/pkg.whl',
                          'some_pkg==1\nsome-pkg==1', ''):
                file.write_text(value)
                with self.assertRaises(ValueError):
                    builder.requirements(file)

    def test_changed_browser_dependency_graph_requires_review(self):
        lock = json.loads((ROOT / 'provisioning/graphics/package-lock.json').read_text())
        lock['packages']['node_modules/extra'] = {}
        with tempfile.TemporaryDirectory() as temporary:
            file = Path(temporary) / 'package-lock.json'
            file.write_text(json.dumps(lock))
            with self.assertRaises(ValueError):
                builder.browser_package(file)

    def test_wrong_build_platform_rejected_before_output_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'not-created'
            with patch.object(builder.platform, 'freedesktop_os_release', return_value={'ID': 'other'}):
                with self.assertRaises(ValueError):
                    builder.build(ROOT, output)
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
