import copy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('storage_plan', ROOT / 'iso/storage_plan.py')
storage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(storage)
DATA_UUID = '4229266e-c564-4bd5-b2db-f4433b5572c5'


class StoragePlanTests(unittest.TestCase):
    def setUp(self):
        self.disk = dict(serial='test-disk', size=128 * storage.GIB, type='disk',
                         removable=False, read_only=False, in_use=False, ptable='gpt',
                         partitions=[
                             dict(number=1, size=storage.MIB, flag='bios_grub'),
                             dict(number=2, size=512 * storage.MIB, flag='boot', fstype='vfat'),
                             dict(number=3, size=storage.ROOT_SIZE, fstype='ext4'),
                             dict(number=4, size=79 * storage.GIB, fstype='btrfs', uuid=DATA_UUID),
                         ])
        self.metadata = dict(product='mindflayer-elderbrain', layout_version=1,
                             data_uuid=DATA_UUID, disk_serial='test-disk',
                             appliance_id='fb7e5cae-d530-4a1b-9138-322ad8fa48d1')

    def preserve(self, inventory=None):
        return storage.plan(inventory or [self.disk], mode='preserve', serial='test-disk',
                            data_uuid=DATA_UUID, metadata=self.metadata)

    def test_fresh_requires_confirmation_and_uses_explicit_serial(self):
        with self.assertRaises(ValueError):
            storage.plan([self.disk], mode='fresh', serial='test-disk')
        for uefi in (False, True):
            config = storage.plan([self.disk], mode='fresh', serial='test-disk',
                                  erase_confirmed=True, uefi=uefi)['config']
            self.assertEqual(config[0]['serial'], 'test-disk')
            self.assertEqual(config[0]['grub_device'], not uefi)
            self.assertEqual(config[4]['size'], -1)
            self.assertEqual(config[-1]['path'], storage.DATA_MOUNT)
            self.assertNotIn('nofail', config[-1]['options'])

    def test_preserve_never_wipes_disk_or_formats_data_or_esp(self):
        before = copy.deepcopy(self.disk)
        config = self.preserve()['config']
        self.assertFalse(any('wipe' in action for action in config))
        for action in config:
            if action['type'] in ('disk', 'partition'):
                self.assertTrue(action['preserve'])
            if action['type'] == 'format':
                self.assertEqual(action['preserve'], action['volume'] != 'partition-3')
        self.assertEqual(config[4]['size'], self.disk['partitions'][3]['size'])
        self.assertEqual(self.disk, before)

    def test_duplicate_serial_and_cloned_filesystem_are_rejected(self):
        with self.assertRaises(ValueError):
            self.preserve([self.disk, copy.deepcopy(self.disk)])
        clone = copy.deepcopy(self.disk)
        clone['serial'] = 'another-disk'
        with self.assertRaises(ValueError):
            self.preserve([self.disk, clone])

    def test_missing_or_unsafe_disk_facts_are_rejected(self):
        for key in ('removable', 'read_only', 'in_use'):
            for value in (True, None, 0):
                with self.subTest(key=key, value=value):
                    disk = copy.deepcopy(self.disk)
                    disk[key] = value
                    with self.assertRaises(ValueError):
                        self.preserve([disk])

    def test_wrong_metadata_is_rejected(self):
        for key in list(self.metadata):
            original = self.metadata.pop(key)
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.preserve()
            self.metadata[key] = original

    def test_invalid_modes_targets_and_small_disks_are_rejected(self):
        for arguments in [dict(mode='automatic', serial='test-disk'),
                          dict(mode='fresh', serial=''),
                          dict(mode='fresh', serial='missing')]:
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                storage.plan([self.disk], erase_confirmed=True, **arguments)
        self.disk['size'] = 64 * storage.GIB
        with self.assertRaises(ValueError):
            self.preserve()

    def test_metadata_must_match_uuid_serial_product_and_version(self):
        for key, value in [('data_uuid', 'wrong'), ('disk_serial', 'another'),
                           ('product', 'another'), ('layout_version', 2),
                           ('layout_version', True), ('appliance_id', 'invalid')]:
            original = self.metadata[key]
            self.metadata[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.preserve()
            self.metadata[key] = original

    def test_legacy_and_unexpected_layouts_are_rejected(self):
        variants = [dict(ptable='dos'), dict(partitions=[])]
        for index, change in [(0, {'size': 2 * storage.MIB}), (1, {'flag': None}),
                              (2, {'fstype': 'btrfs'}), (3, {'fstype': 'ext4'}),
                              (3, {'uuid': 'wrong'}), (3, {'number': 3})]:
            partitions = copy.deepcopy(self.disk['partitions'])
            partitions[index].update(change)
            variants.append(dict(partitions=partitions))
        for change in variants:
            disk = {**self.disk, **change}
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.preserve([disk])


if __name__ == '__main__':
    unittest.main()
