import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'appliance/lib'))
from release_targets import bindings, sources, targets
from restore_transaction import RestoreTransaction

ROOT = Path(__file__).resolve().parents[1]


class DeploymentTargetTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.host, self.tree = self.root / 'host', self.root / 'candidate'
        self.host.mkdir()
        self.tree.mkdir()
        for name, relative in bindings().items():
            target, source = self.host / name, self.tree / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            source.parent.mkdir(parents=True, exist_ok=True)
            if relative == 'runtime':
                target.mkdir()
                source.mkdir()
                (target / 'VERSION').write_text('old')
                (source / 'VERSION').write_text('new')
            else:
                target.write_text('old: ' + name)
                source.write_text('new: ' + relative)
        self.settings = self.root / 'persistent-settings'
        self.settings.mkdir(mode=0o700)
        (self.settings / 'appliance.env').write_text('PRIVATE=preserved')
        (self.settings / 'appliance.env').chmod(0o600)
        for runtime in (self.host / 'opt/mindflayer-elderbrain', self.tree / 'runtime'):
            (runtime / 'appliance.env').symlink_to(self.settings / 'appliance.env')
        self.override = self.host / 'etc/systemd/system/elderbrain-stack.service.d/99-user.conf'
        self.override.write_text('user override')

    def test_fixed_map_covers_packaged_units_without_targeting_user_configuration(self):
        inventory = json.loads((ROOT / 'release/host-files.json').read_text())
        packaged = {entry['path'] for entry in inventory}
        self.assertTrue(set(bindings().values()) - {'runtime'} <= packaged)
        self.assertTrue({name for name in packaged if name.startswith('units/')} <= set(bindings().values()))
        self.assertFalse(any(name.startswith(('var/', 'etc/ssh/')) for name in bindings()))
        self.assertNotIn('templates/appliance.env', bindings().values())
        self.assertNotIn('templates/sway.conf', bindings().values())

    def test_switch_and_rollback_preserve_settings_and_user_overrides(self):
        selected = sources(self.tree, self.host)
        transaction = RestoreTransaction(self.root / 'transaction.json', targets(self.host))
        transaction.prepare(selected)
        transaction.apply()
        self.assertEqual((self.host / 'opt/mindflayer-elderbrain/VERSION').read_text(), 'new')
        self.assertEqual(self.override.read_text(), 'user override')
        self.assertEqual((self.host / 'opt/mindflayer-elderbrain/appliance.env').read_text(), 'PRIVATE=preserved')
        transaction.rollback()
        self.assertEqual((self.host / 'opt/mindflayer-elderbrain/VERSION').read_text(), 'old')
        self.assertEqual(self.override.read_text(), 'user override')
        self.assertEqual((self.settings / 'appliance.env').stat().st_mode & 0o777, 0o600)
        for name, relative in bindings().items():
            if relative != 'runtime':
                self.assertEqual((self.host / name).read_text(), 'old: ' + name)

    def test_aliased_target_rejected_without_touching_destination(self):
        target = self.host / 'usr/local/sbin/elderbrain'
        target.unlink()
        target.symlink_to(self.settings / 'appliance.env')
        with self.assertRaisesRegex(ValueError, 'target'):
            sources(self.tree, self.host)
        self.assertEqual((self.settings / 'appliance.env').read_text(), 'PRIVATE=preserved')

    def test_missing_parent_is_not_silently_created(self):
        target = self.host / 'etc/opt/chrome/policies/managed/elderbrain.json'
        target.unlink()
        target.parent.rmdir()
        with self.assertRaisesRegex(ValueError, 'target'):
            sources(self.tree, self.host)
        self.assertFalse(target.parent.exists())

    def test_untrusted_source_link_and_writable_source_rejected(self):
        source = self.tree / 'bin/elderbrain'
        source.chmod(0o666)
        with self.assertRaisesRegex(ValueError, 'source'):
            sources(self.tree, self.host)

        source.unlink()
        source.symlink_to(self.settings / 'appliance.env')
        with self.assertRaisesRegex(ValueError, 'source'):
            sources(self.tree, self.host)

    def test_writable_target_parent_rejected(self):
        (self.host / 'usr/local/sbin').chmod(0o777)
        with self.assertRaisesRegex(ValueError, 'target parent'):
            sources(self.tree, self.host)


if __name__ == '__main__':
    unittest.main()
