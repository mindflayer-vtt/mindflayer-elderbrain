from pathlib import Path
import tempfile
import unittest

from provisioning.runtime_settings import configure, FILES


class RuntimeSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.payload, self.runtime, self.state = [self.root / name for name in ('payload', 'runtime', 'state')]
        for name, (relative, _) in FILES.items():
            path = self.payload / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('default ' + name)

    def configure(self, mode):
        configure(self.payload, self.runtime, self.state, mode=mode)

    def test_fresh_aliases_and_preserve_keep_custom_values(self):
        self.configure('fresh')
        for name, (_, permissions) in FILES.items():
            alias = self.runtime / name
            self.assertTrue(alias.is_symlink())
            self.assertEqual(alias.stat().st_mode & 0o777, permissions)
            alias.write_text('custom ' + name)
            alias.unlink()  # simulate OS reinstallation, not data removal
        self.configure('preserve')
        for name in FILES:
            self.assertEqual((self.runtime / name).read_text(), 'custom ' + name)

    def test_missing_preserved_settings_never_seed_defaults(self):
        with self.assertRaises(ValueError):
            self.configure('preserve')
        self.assertFalse(self.state.exists())

    def test_atomic_canonical_replacement_visible_through_alias(self):
        self.configure('fresh')
        canonical = self.state / 'host/runtime/appliance.env'
        replacement = canonical.with_suffix('.incoming')
        replacement.write_text('restored')
        replacement.replace(canonical)
        self.assertEqual((self.runtime / 'appliance.env').read_text(), 'restored')

    def test_conflicting_os_file_is_not_overwritten(self):
        self.configure('fresh')
        alias = self.runtime / 'appliance.env'
        alias.unlink()
        alias.write_text('conflicting user setting')
        with self.assertRaises(ValueError):
            self.configure('preserve')
        self.assertEqual(alias.read_text(), 'conflicting user setting')


if __name__ == '__main__':
    unittest.main()
