from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from provisioning.storage_initialize import initialize
from appliance.lib.storage_guard import MARKER


class StorageInitializeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = self.root / 'data'
        self.target.mkdir()
        self.expected = self.root / 'etc/storage.json'
        self.identity = dict(product='mindflayer-elderbrain', layout_version=1,
                             appliance_id='fb7e5cae-d530-4a1b-9138-322ad8fa48d1',
                             data_uuid='4229266e-c564-4bd5-b2db-f4433b5572c5', disk_serial='test')
        self.mount = {'filesystems': [dict(target=str(self.target), fstype='btrfs',
                                          fsroot='/', uuid=self.identity['data_uuid'], options='rw')]}
        self.receipt = dict(version=1, mode='preserve', serial='test', identity=self.identity)
        self.read = Mock(return_value=self.identity)
        self.publish = Mock()

    def initialize(self):
        return initialize(self.receipt, self.mount, target=str(self.target),
                          expected_path=self.expected, read=self.read, publish=self.publish)

    def test_preserve_reuses_identity_and_never_writes_marker(self):
        self.assertEqual(self.initialize(), self.identity)
        self.read.assert_called_once_with(self.target / MARKER)
        self.publish.assert_called_once_with(self.expected, self.identity)

    def test_missing_marker_never_recreated(self):
        self.read.side_effect = FileNotFoundError()
        with self.assertRaises(FileNotFoundError):
            self.initialize()
        self.publish.assert_not_called()

    def test_missing_or_wrong_mount_never_reads_or_writes_identity(self):
        self.mount['filesystems'][0]['target'] = '/'
        with self.assertRaises(ValueError):
            self.initialize()
        self.read.assert_not_called()
        self.publish.assert_not_called()

    def test_fresh_creates_marker_then_installed_identity(self):
        self.receipt.update(mode='fresh', identity=None)
        identity = self.initialize()
        self.assertEqual(identity['data_uuid'], self.identity['data_uuid'])
        self.assertEqual([call.args[0] for call in self.publish.call_args_list],
                         [self.target / MARKER, self.expected])
        self.read.assert_not_called()

    def test_fresh_refuses_existing_user_data(self):
        self.receipt.update(mode='fresh', identity=None)
        (self.target / 'user-data').write_text('must survive')
        with self.assertRaises(ValueError):
            self.initialize()
        self.publish.assert_not_called()

    def test_preserve_changed_marker_refused(self):
        self.read.return_value = {**self.identity, 'disk_serial': 'other'}
        with self.assertRaises(ValueError):
            self.initialize()
        self.publish.assert_not_called()

    def test_installer_guards_before_directory_creation_and_includes_docker(self):
        root = Path(__file__).resolve().parents[1]
        script = (root / 'provisioning/install.sh').read_text()
        self.assertLess(script.index('python3 "$PAYLOAD_DIR/appliance/lib/storage_guard.py"'),
                        script.index('"$STATE"/{foundry'))
        self.assertIn('for storage_writer in docker elderbrain-stack', script)
        unit = (root / 'provisioning/systemd/storage-required.conf').read_text()
        self.assertIn('Requires=elderbrain-storage.service', unit)
        self.assertIn('After=elderbrain-storage.service', unit)
        self.assertIn('BindsTo=var-lib-mindflayer\\x2delderbrain.mount', unit)


if __name__ == '__main__':
    unittest.main()
