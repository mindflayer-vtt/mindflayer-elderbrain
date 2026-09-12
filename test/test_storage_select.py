import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from iso.storage_select import choose, configure, atomic_write
from . import test_storage_plan as fixtures


class StorageSelectionTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.StoragePlanTests()
        fixture.setUp()
        self.disk = fixture.disk
        self.identity = fixture.metadata

    def choose(self, answers):
        return choose([self.disk], ask=Mock(side_effect=answers), tell=Mock())

    def test_fresh_has_no_default_and_needs_exact_erasure_phrase(self):
        for answers in [[''], ['fresh', 'test-disk', 'yes'],
                        ['fresh', 'test-disk', 'ERASE other']]:
            with self.assertRaises(ValueError):
                self.choose(answers)
        selected = self.choose(['fresh', 'test-disk', 'ERASE test-disk'])
        self.assertTrue(selected['erase_confirmed'])

    def test_preserve_needs_uuid_and_os_reinstall_confirmation(self):
        selected = self.choose(['preserve', 'test-disk', fixtures.DATA_UUID,
                                'REINSTALL OS test-disk'])
        self.assertEqual(selected['data_uuid'], fixtures.DATA_UUID)
        self.assertFalse(selected['erase_confirmed'])

    def test_wrong_and_ambiguous_serials_rejected(self):
        with self.assertRaises(ValueError):
            self.choose(['fresh', 'unknown'])
        with self.assertRaises(ValueError):
            choose([self.disk, self.disk], ask=Mock(side_effect=['fresh', 'test-disk']), tell=Mock())

    def test_document_keeps_other_installer_settings(self):
        document = {'autoinstall': {'version': 1, 'identity': {'hostname': 'elderbrain'},
                                    'storage': {'layout': {'name': 'direct'}}}}
        original = copy.deepcopy(document)
        selected = self.choose(['fresh', 'test-disk', 'ERASE test-disk'])
        updated, receipt = configure(document, selected, inventory_probe=lambda: [self.disk])
        self.assertEqual(document, original)
        self.assertEqual(updated['autoinstall']['identity'], original['autoinstall']['identity'])
        self.assertNotIn('layout', updated['autoinstall']['storage'])
        self.assertEqual(receipt['mode'], 'fresh')

    def test_private_atomic_output_and_symlink_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'receipt.json'
            atomic_write(path, 'first')
            atomic_write(path, 'second')
            self.assertEqual(path.read_text(), 'second')
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            link = Path(directory) / 'link'
            link.symlink_to(path)
            with self.assertRaises(ValueError):
                atomic_write(link, 'wrong')
            self.assertEqual(path.read_text(), 'second')
            self.assertEqual(len(list(Path(directory).iterdir())), 2)

    def test_subiquity_normalized_inner_document_is_supported(self):
        document = {'version': 1, 'identity': {'hostname': 'elderbrain'}, 'storage': {'config': []}}
        selected = self.choose(['fresh', 'test-disk', 'ERASE test-disk'])
        updated, receipt = configure(document, selected, inventory_probe=lambda: [self.disk])
        self.assertNotIn('autoinstall', updated)
        self.assertEqual(updated['identity'], document['identity'])
        self.assertEqual(updated['storage']['config'][0]['serial'], 'test-disk')
        self.assertEqual(receipt['mode'], 'fresh')


if __name__ == '__main__':
    unittest.main()
