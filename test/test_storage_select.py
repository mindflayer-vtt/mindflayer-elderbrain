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

    def test_fresh_has_no_default_and_needs_explicit_erasure_phrase(self):
        for answers in [['cancel'], ['fresh', 'cancel']]:
            with self.assertRaises(ValueError):
                self.choose(answers)
        selected = self.choose(['FrEsH', '1', 'erase disk 1'])
        self.assertTrue(selected['erase_confirmed'])
        self.assertEqual(selected['serial'], 'test-disk')

    def test_invalid_answers_restart_selection_without_a_traceback(self):
        tell = Mock()
        selected = choose([self.disk], ask=Mock(side_effect=[
            'wrong', 'fresh', '0', 'fresh', '1', 'yes',
            'fresh', '1', 'ERASE DISK 1']), tell=tell)
        self.assertTrue(selected['erase_confirmed'])
        output = '\n'.join(call.args[0] for call in tell.call_args_list)
        self.assertIn('Invalid installation mode. No changes made; starting over.', output)
        self.assertIn('Invalid disk number. No changes made; starting over.', output)
        self.assertIn('Confirmation did not match. No changes made; starting over.', output)

    def test_preserve_needs_uuid_and_os_reinstall_confirmation(self):
        selected = self.choose(['preserve', '1', '4', 'REINSTALL OS DISK 1'])
        self.assertEqual(selected['data_uuid'], fixtures.DATA_UUID)
        self.assertFalse(selected['erase_confirmed'])

    def test_wrong_number_and_ambiguous_or_unsafe_serials_are_not_selectable(self):
        with self.assertRaises(ValueError):
            self.choose(['fresh', '2', 'cancel'])
        with self.assertRaises(ValueError):
            choose([self.disk, self.disk], ask=Mock(side_effect=['fresh']), tell=Mock())
        unsafe = copy.deepcopy(self.disk)
        unsafe['removable'] = True
        with self.assertRaisesRegex(ValueError, 'No unused'):
            choose([unsafe], ask=Mock(side_effect=['fresh']), tell=Mock())

    def test_numbered_disk_selection_resolves_exact_serial_without_transcription(self):
        first = copy.deepcopy(self.disk)
        first.update(path='/dev/sda', model='First disk', serial='first-serial')
        second = copy.deepcopy(self.disk)
        second.update(path='/dev/sdb', model='Second disk', serial='second-serial')
        tell = Mock()
        selected = choose([first, second], ask=Mock(side_effect=[
            'fresh', '2', 'ERASE DISK 2']), tell=tell)
        self.assertEqual(selected['serial'], 'second-serial')
        output = '\n'.join(call.args[0] for call in tell.call_args_list)
        self.assertIn('1. ', output)
        self.assertIn('2. ', output)
        self.assertIn('Second disk', output)

    def test_preserve_partition_selection_requires_displayed_btrfs_number(self):
        for answer in ('', '3', fixtures.DATA_UUID):
            with self.subTest(answer=answer), self.assertRaises(ValueError):
                self.choose(['preserve', '1', answer, 'cancel'])

    def test_document_keeps_other_installer_settings(self):
        document = {'autoinstall': {'version': 1, 'identity': {'hostname': 'elderbrain'},
                                    'storage': {'layout': {'name': 'direct'}}}}
        original = copy.deepcopy(document)
        selected = self.choose(['fresh', '1', 'ERASE DISK 1'])
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
        selected = self.choose(['fresh', '1', 'ERASE DISK 1'])
        updated, receipt = configure(document, selected, inventory_probe=lambda: [self.disk])
        self.assertNotIn('autoinstall', updated)
        self.assertEqual(updated['identity'], document['identity'])
        self.assertEqual(updated['storage']['config'][0]['serial'], 'test-disk')
        self.assertEqual(receipt['mode'], 'fresh')


if __name__ == '__main__':
    unittest.main()
