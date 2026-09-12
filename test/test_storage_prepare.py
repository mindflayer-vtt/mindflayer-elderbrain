import copy
import unittest
from unittest.mock import Mock

from iso.storage_prepare import prepare
import test_storage_plan as fixtures


class StoragePrepareTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.StoragePlanTests()
        fixture.setUp()
        self.disk = fixture.disk
        self.disk['partitions'][3]['path'] = '/dev/vda4'
        self.identity = fixture.metadata
        self.probe = Mock(return_value=[self.disk])
        self.reader = Mock(return_value=self.identity)

    def prepare(self):
        return prepare(mode='preserve', serial='test-disk', data_uuid=fixtures.DATA_UUID,
                       inventory_probe=self.probe, marker_reader=self.reader)

    def test_preserve_requires_real_marker_and_second_probe(self):
        result = self.prepare()
        self.assertEqual(result['identity'], self.identity)
        self.assertEqual(self.probe.call_count, 2)
        self.reader.assert_called_once_with('/dev/vda4', fixtures.DATA_UUID)

    def test_busy_or_wrong_layout_never_mounted(self):
        self.disk['in_use'] = True
        with self.assertRaises(ValueError):
            self.prepare()
        self.reader.assert_not_called()

    def test_disk_change_during_inspection_rejected(self):
        changed = copy.deepcopy(self.disk)
        changed['partitions'][3]['path'] = '/dev/vdb4'
        self.probe.side_effect = [[self.disk], [changed]]
        with self.assertRaises(ValueError):
            self.prepare()

    def test_new_clone_after_inspection_rejected(self):
        clone = copy.deepcopy(self.disk)
        clone['serial'] = 'clone'
        self.probe.side_effect = [[self.disk], [self.disk, clone]]
        with self.assertRaises(ValueError):
            self.prepare()

    def test_false_marker_is_rejected(self):
        self.reader.return_value = {**self.identity, 'disk_serial': 'other'}
        with self.assertRaises(ValueError):
            self.prepare()

    def test_fresh_requires_confirmation_without_mounting(self):
        with self.assertRaises(ValueError):
            prepare(mode='fresh', serial='test-disk', inventory_probe=self.probe,
                    marker_reader=self.reader)
        result = prepare(mode='fresh', serial='test-disk', erase_confirmed=True,
                         inventory_probe=self.probe, marker_reader=self.reader)
        self.assertIsNone(result['identity'])
        self.reader.assert_not_called()


if __name__ == '__main__':
    unittest.main()
