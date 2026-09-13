import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('storage_probe', ROOT / 'iso/storage_probe.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class StorageProbeTests(unittest.TestCase):
    def setUp(self):
        self.partition = dict(path='/dev/vda1', type='part', partn=1, size=1024**2,
                              parttype='21686148-6449-6e6f-744e-656564454649',
                              fstype=None, uuid=None, mountpoints=[None])
        self.disk = dict(path='/dev/vda', type='disk', serial='vm-test', size=128*1024**3,
                         model='QEMU HARDDISK',
                         rm=False, ro=False, pttype='gpt', mountpoints=[None],
                         children=[self.partition])

    def result(self):
        return probe.normalize({'blockdevices': [self.disk]})[0]

    def test_explicit_tree_command_and_normalization(self):
        run = Mock(side_effect=[SimpleNamespace(), SimpleNamespace(
            stdout=json.dumps({'blockdevices': [self.disk]}))])
        result = probe.probe(run)
        self.assertIn('--tree', run.call_args_list[1].args[0])
        self.assertEqual(result[0]['partitions'][0]['flag'], 'bios_grub')
        self.assertIs(result[0]['in_use'], False)
        self.assertEqual(result[0]['serial'], 'vm-test')
        self.assertEqual(result[0]['model'], 'QEMU HARDDISK')
        self.assertIn('MODEL', probe.COLUMNS)

    def test_mounted_swap_and_unknown_mount_information_are_busy(self):
        for mounts in (['/'], ['/cdrom'], ['[SWAP]'], None):
            with self.subTest(mounts=mounts):
                self.partition['mountpoints'] = mounts
                self.assertTrue(self.result()['in_use'])
        self.partition.pop('mountpoints')
        self.assertTrue(self.result()['in_use'])

    def test_holders_are_busy_even_when_unmounted(self):
        for kind in ('crypt', 'lvm', 'raid1', 'mpath'):
            self.partition['children'] = [dict(type=kind, mountpoints=[])]
            self.assertTrue(self.result()['in_use'])

    def test_unknown_partition_type_cannot_look_like_linux_data(self):
        for kind in (None, 'ebd0a0a2-b9e5-4433-87c0-68b6b72699c7'):
            self.partition['parttype'] = kind
            self.assertEqual(self.result()['partitions'][0]['flag'], 'unsupported')

    def test_flattened_inventory_is_rejected(self):
        disk = copy.deepcopy(self.disk)
        disk.pop('children')
        with self.assertRaises(ValueError):
            probe.normalize({'blockdevices': [disk, self.partition]})

    def test_missing_safety_booleans_are_not_inferred(self):
        self.disk.pop('rm')
        self.disk.pop('ro')
        self.assertIsNone(self.result()['removable'])
        self.assertIsNone(self.result()['read_only'])


if __name__ == '__main__':
    unittest.main()
