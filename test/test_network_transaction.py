import importlib.util
from pathlib import Path
import tempfile
import unittest
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'appliance/lib'))
spec = importlib.util.spec_from_file_location('network_transaction', ROOT / 'appliance/lib/network_transaction.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class NetworkTransactionTests(unittest.TestCase):
    def test_added_and_removed_sources_roll_back_on_timeout(self):
        self.store.stage({'50-network.yaml': {'before': self.before, 'after': None},
                          '70-restored.yaml': {'before': None, 'after': self.after}}, 'ens3', seconds=15)
        self.store.tick()
        added = self.netplan / '70-restored.yaml'
        self.assertFalse(self.source.exists())
        self.assertEqual(added.read_bytes(), self.after)
        self.clock += 16
        self.assertEqual(self.store.tick()['phase'], 'rolled-back')
        self.assertEqual(self.source.read_bytes(), self.before)
        self.assertEqual(self.source.stat().st_mode & 0o777, 0o640)
        self.assertFalse(added.exists())

    def test_added_and_removed_sources_can_be_confirmed(self):
        staged = self.store.stage({'50-network.yaml': {'before': self.before, 'after': None},
                                   '70-restored.yaml': {'before': None, 'after': self.after}}, 'ens3')
        self.store.tick()
        self.assertEqual(self.store.confirm(staged['id'], 'trusted-destination')['phase'], 'confirmed')
        self.assertFalse(self.source.exists())
        self.assertEqual((self.netplan / '70-restored.yaml').read_bytes(), self.after)

    def test_external_file_created_after_deletion_blocks_rollback(self):
        self.store.stage({'50-network.yaml': {'before': self.before, 'after': None}}, 'ens3', seconds=15)
        self.store.tick()
        self.source.write_bytes(b'external replacement')
        self.clock += 16
        with self.assertRaisesRegex(ValueError, 'External edit'):
            self.store.tick()
        self.assertEqual(self.source.read_bytes(), b'external replacement')

    def test_partial_addition_is_recovered_after_process_loss(self):
        self.store.stage({'50-network.yaml': {'before': self.before, 'after': None},
                          '70-restored.yaml': {'before': None, 'after': self.after}}, 'ens3')
        record = self.store.read()
        record['phase'] = 'applying'
        self.store.write(record)
        added = record['files']['70-restored.yaml']
        self.store.replace('70-restored.yaml', added['after'], added['before'])
        self.store.tick()
        self.assertEqual(self.source.read_bytes(), self.before)
        self.assertFalse((self.netplan / '70-restored.yaml').exists())

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.netplan = root / 'netplan'
        self.netplan.mkdir()
        self.source = self.netplan / '50-network.yaml'
        self.before = b'# private original\nnetwork: {version: 2}\n'
        self.after = b'network: {version: 2, ethernets: {ens3: {dhcp4: true}}}\n'
        self.source.write_bytes(self.before)
        self.source.chmod(0o640)
        self.clock, self.monotonic = 1000, 100
        self.applied = []
        self.store = module.NetworkTransaction(root / 'transaction', self.netplan,
            apply=lambda: self.applied.append('apply'), verify_confirmation=lambda proof, record: proof == 'trusted-destination',
            clock=lambda: self.clock, monotonic=lambda: self.monotonic, boot='boot-one')

    def stage(self):
        return self.store.stage({'50-network.yaml': {'before': self.before, 'after': self.after}}, 'ens3', seconds=15)

    def test_staging_is_durable_and_does_not_apply_until_worker_ticks(self):
        staged = self.stage()
        self.assertEqual(staged['phase'], 'staged')
        self.assertEqual(self.source.read_bytes(), self.before)
        self.assertEqual(self.applied, [])
        self.assertNotIn('files', staged)
        self.assertEqual((self.store.state / 'state.json').stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.store.tick()['phase'], 'pending')
        self.assertEqual(self.source.read_bytes(), self.after)
        self.assertEqual(self.source.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.applied, ['apply'])

    def test_deadline_restores_exact_bytes_and_permissions(self):
        self.stage()
        self.store.tick()
        self.clock += 16
        self.assertEqual(self.store.tick()['phase'], 'rolled-back')
        self.assertEqual(self.source.read_bytes(), self.before)
        self.assertEqual(self.source.stat().st_mode & 0o777, 0o640)
        self.assertEqual(self.applied, ['apply', 'apply'])
        self.assertNotIn('files', self.store.read())

    def test_confirmation_requires_matching_id_and_trusted_new_address(self):
        staged = self.stage()
        self.store.tick()
        for identifier, proof in [('wrong', 'trusted-destination'), (staged['id'], 'forged-host-header')]:
            with self.assertRaises(ValueError):
                self.store.confirm(identifier, proof)
        self.assertEqual(self.store.confirm(staged['id'], 'trusted-destination')['phase'], 'confirmed')
        self.clock += 100
        self.assertEqual(self.store.tick()['phase'], 'confirmed')
        self.assertEqual(self.source.read_bytes(), self.after)

    def test_crash_during_multi_file_application_is_recoverable(self):
        second = self.netplan / '90-network.yaml'
        second.write_bytes(self.before)
        self.store.stage({name: {'before': self.before, 'after': self.after}
                          for name in ('50-network.yaml', '90-network.yaml')}, 'ens3')
        record = self.store.read()
        record['phase'] = 'applying'
        self.store.write(record)
        self.store.replace('50-network.yaml', record['files']['50-network.yaml']['after'], record['files']['50-network.yaml']['before'])
        self.assertEqual(self.store.tick()['phase'], 'rolled-back')
        self.assertEqual(self.source.read_bytes(), self.before)
        self.assertEqual(second.read_bytes(), self.before)

    def test_restart_failure_stays_retryable_and_external_edits_are_not_overwritten(self):
        self.stage()
        self.store.tick()
        self.clock += 16
        self.source.write_bytes(b'external edit')
        with self.assertRaisesRegex(ValueError, 'External edit'):
            self.store.tick()
        self.assertEqual(self.source.read_bytes(), b'external edit')
        self.assertEqual(self.store.read()['phase'], 'rolling-back')
        self.source.write_bytes(self.after)
        self.store.apply = lambda: (_ for _ in ()).throw(RuntimeError('apply unavailable'))
        with self.assertRaises(RuntimeError):
            self.store.tick()
        self.assertEqual(self.source.read_bytes(), self.before)
        self.store.apply = lambda: None
        self.assertEqual(self.store.tick()['phase'], 'rolled-back')

    def test_reboot_clock_change_and_staged_cancellation(self):
        staged = self.stage()
        self.store.cancel(staged['id'])
        self.assertEqual(self.applied, [])
        self.stage()
        self.store.tick()
        self.clock -= 1000
        self.monotonic += 16
        self.assertEqual(self.store.tick()['phase'], 'rolled-back')
        self.stage()
        self.store.tick()
        self.store.boot = 'boot-two'
        self.assertEqual(self.store.tick()['phase'], 'rolled-back')

    def test_pre_apply_conflict_is_discarded_without_network_mutation(self):
        self.stage()
        self.source.write_bytes(b'external edit')
        with self.assertRaises(ValueError):
            self.store.tick()
        self.assertEqual(self.store.read()['phase'], 'rolled-back')
        self.assertEqual(self.source.read_bytes(), b'external edit')
        self.assertEqual(self.applied, [])

    def test_paths_symlinks_and_overlapping_transactions_are_rejected(self):
        self.stage()
        with self.assertRaises(ValueError):
            self.stage()
        with self.assertRaises(ValueError):
            self.store.filename('../outside.yaml')
        symlink = self.netplan / 'linked.yaml'
        symlink.symlink_to(self.source)
        with self.assertRaises(OSError):
            self.store.file('linked.yaml')

    def test_whole_hierarchy_is_rechecked_before_application(self):
        changes = {'50-network.yaml': {'before': self.before, 'after': self.after}}
        with self.assertRaisesRegex(ValueError, 'before staging'):
            self.store.stage(changes, 'ens3', fingerprint='a' * 64)
        self.store.verify_sources = lambda value: value == 'a' * 64
        self.store.stage(changes, 'ens3', fingerprint='a' * 64)
        self.store.verify_sources = lambda value: False
        with self.assertRaisesRegex(ValueError, 'before application'):
            self.store.tick()
        self.assertEqual(self.store.read()['phase'], 'rolled-back')
        self.assertEqual(self.source.read_bytes(), self.before)
        self.assertEqual(self.applied, [])

    def test_boot_recovery_regenerates_without_applying_networking(self):
        self.stage()
        self.store.tick()
        generated = []
        self.assertEqual(self.store.recover_boot(lambda: generated.append(True))['phase'], 'rolled-back')
        self.assertEqual(generated, [True])
        self.assertEqual(self.applied, ['apply'])
        self.assertEqual(self.source.read_bytes(), self.before)
        self.assertEqual(self.source.stat().st_mode & 0o777, 0o640)
        self.store.recover_boot(lambda: self.fail('Recovery must be idempotent'))

    def test_boot_recovery_failure_remains_retryable(self):
        self.stage()
        self.store.tick()
        with self.assertRaises(RuntimeError):
            self.store.recover_boot(lambda: (_ for _ in ()).throw(RuntimeError('generate failed')))
        self.assertEqual(self.store.read()['phase'], 'rolling-back')
        self.assertEqual(self.source.read_bytes(), self.before)
        self.store.recover_boot(lambda: None)
        self.assertEqual(self.store.read()['phase'], 'rolled-back')

    def test_boot_recovery_preserves_confirmed_and_discards_unapplied_changes(self):
        self.stage()
        self.store.recover_boot(lambda: self.fail('No generation for unapplied candidate'))
        staged = self.stage()
        self.store.tick()
        self.store.confirm(staged['id'], 'trusted-destination')
        self.store.recover_boot(lambda: self.fail('Confirmed changes must survive boot'))
        self.assertEqual(self.source.read_bytes(), self.after)

    def test_confirmation_binding_is_private_and_removed_on_terminal_state(self):
        binding = {'digest': 'a' * 64, 'mode': 'dhcp', 'address': None}
        changes = {'50-network.yaml': {'before': self.before, 'after': self.after}}
        staged = self.store.stage(changes, 'ens3', confirmation=binding)
        self.assertNotIn('confirmation', staged)
        self.assertEqual(self.store.read()['confirmation'], binding)
        self.store.cancel(staged['id'])
        self.assertNotIn('confirmation', self.store.read())
        staged = self.store.stage(changes, 'ens3', confirmation=binding)
        self.store.tick()
        self.store.confirm(staged['id'], 'trusted-destination')
        self.assertNotIn('confirmation', self.store.read())

    def test_invalid_confirmation_binding_is_rejected_without_staging(self):
        changes = {'50-network.yaml': {'before': self.before, 'after': self.after}}
        for binding in ({}, {'digest': 'a' * 64, 'mode': 'dhcp', 'address': '10.0.2.20'},
                        {'digest': 'bad', 'mode': 'dhcp', 'address': None}):
            with self.assertRaises(ValueError):
                self.store.stage(changes, 'ens3', confirmation=binding)
        self.assertIsNone(self.store.read())
