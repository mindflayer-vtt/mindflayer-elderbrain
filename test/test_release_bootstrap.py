import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test.test_release_prepare as preparation_fixture
from backup_service import Maintenance, save_record
import release_bootstrap as bootstrap
from release_staging import stage


class BootstrapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        preparation_fixture.ReleasePrepareTests.setUpClass()
        cls.addClassCleanup(preparation_fixture.ReleasePrepareTests.doClassCleanups)

    def setUp(self):
        self.fixture = preparation_fixture.ReleasePrepareTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root / 'host'
        self.root.mkdir()
        self.state = self.root / 'var/lib/mindflayer-elderbrain'
        self.state.mkdir(parents=True, mode=0o700)
        self.storage = patch.object(bootstrap, 'persistent_identity', return_value='fixture-storage')
        self.storage.start()
        self.addCleanup(self.storage.stop)
        bundle = self.fixture.bundle
        self.tree = self.enterContext(stage(bundle / 'elderbrain-host.tar.zst',
            (bundle / 'manifest.json').read_bytes(), (bundle / 'manifest.sig').read_bytes(),
            self.fixture.public, self.fixture.paths, parent=self.fixture.root))[1]
        self.units = self.root / 'etc/systemd/system'
        self.units.mkdir(parents=True)
        self.previous = self.units / 'elderbrain-storage.service'
        self.previous.write_text('old storage unit\n')
        self.override = self.units / 'elderbrain-storage.service.d/user.conf'
        self.override.parent.mkdir()
        self.override.write_text('user-owned override\n')

    def install(self):
        return bootstrap.install(self.tree, self.fixture.paths, state=self.state, host_root=self.root)

    def test_install_preserves_previous_bytes_and_unrelated_override(self):
        result = self.install()
        self.assertEqual(result['state'], 'installed')
        self.assertFalse(result['activationReady'])
        recovery = self.root / 'usr/lib/elderbrain-recovery'
        previous = result['files']['etc/systemd/system/elderbrain-storage.service']
        self.assertEqual((recovery / result['history'] / previous['backup']).read_text(), 'old storage unit\n')
        self.assertEqual(self.override.read_text(), 'user-owned override\n')
        for target, source in bootstrap.files().items():
            self.assertEqual((self.root / target).read_bytes(), (self.tree / source).read_bytes())
        for name in bootstrap.UNITS:
            self.assertEqual((self.units / 'multi-user.target.wants' / name).resolve(), self.units / name)
        again = self.install()
        self.assertEqual(again['bundle'], result['bundle'])
        self.assertNotEqual(again['history'], result['history'])
        self.assertTrue((recovery / result['history'] / 'previous.json').exists())

    def test_unfinished_maintenance_keeps_boot_files_and_selector_unchanged(self):
        maintenance = self.state / 'maintenance'
        maintenance.mkdir(mode=0o700)
        save_record(maintenance / 'maintenance.json', {'state': 'working'})
        with self.assertRaisesRegex(RuntimeError, 'unfinished maintenance'):
            self.install()
        self.assertEqual(self.previous.read_text(), 'old storage unit\n')
        self.assertFalse((self.root / 'usr/lib/elderbrain-recovery/active.json').exists())

    def test_symlinked_target_and_conflicting_enablement_rejected_before_mutation(self):
        self.previous.unlink()
        self.previous.symlink_to(self.override)
        with self.assertRaisesRegex(ValueError, 'Unsafe bootstrap target'):
            self.install()
        self.assertFalse((self.root / 'usr').exists())
        self.previous.unlink()
        wants = self.units / 'multi-user.target.wants'
        wants.mkdir()
        (wants / bootstrap.UNITS[0]).symlink_to('../unrelated.service')
        with self.assertRaisesRegex(ValueError, 'Unexpected bootstrap enablement'):
            self.install()
        self.assertFalse((self.root / 'usr').exists())

    def test_missing_storage_does_not_create_bootstrap_directories(self):
        with patch.object(bootstrap, 'persistent_identity', side_effect=ValueError('missing storage')):
            with self.assertRaisesRegex(ValueError, 'missing storage'):
                self.install()
        self.assertFalse((self.root / 'usr').exists())
        with patch.object(bootstrap, 'persistent_identity', return_value=None):
            with self.assertRaisesRegex(ValueError, 'requires verified persistent storage'):
                self.install()
        self.assertFalse((self.root / 'usr').exists())

    def test_trusted_provisioning_payload_installs_before_writer_enablement(self):
        from provisioning.recovery_bootstrap import provision
        result = provision(host_root=self.root)
        self.assertEqual(result['state'], 'installed')
        self.assertFalse(result['activationReady'])
        source = Path(__file__).resolve().parents[1] / 'provisioning/install.sh'
        script = source.read_text()
        self.assertLess(script.index('python3 -m provisioning.host_persistence'),
                        script.index('provisioning/recovery_bootstrap.py'))
        self.assertLess(script.index('provisioning/recovery_bootstrap.py'),
                        script.index('systemctl daemon-reload'))

    def test_maintenance_remains_locked_through_file_publication(self):
        original = bootstrap.publish
        observed = []
        def checked(path, value, mode):
            maintenance = Maintenance(self.state / 'maintenance', None)
            with self.assertRaisesRegex(RuntimeError, 'Another maintenance'):
                with maintenance.locked():
                    self.fail('Bootstrap released maintenance lock before publication')
            observed.append(path)
            return original(path, value, mode)
        with patch.object(bootstrap, 'publish', side_effect=checked):
            self.install()
        self.assertIn(self.previous, observed)

    def test_unreviewed_or_aliased_sources_are_rejected(self):
        source = self.tree / 'bootstrap/recovery-launcher.py'
        source.unlink()
        source.symlink_to(self.override)
        with self.assertRaisesRegex(ValueError, 'outside reviewed inventory'):
            self.install()
        self.assertFalse((self.root / 'usr').exists())

    def test_installed_proof_checks_bundle_files_gates_and_enablement(self):
        result = self.install()
        def proof():
            return bootstrap.verify_installed(self.tree, self.fixture.paths, host_root=self.root)
        self.assertEqual(proof(), {'bundle': result['bundle']})
        gate = self.units / 'docker.service.d/20-update-recovery.conf'
        original = gate.read_bytes()
        gate.write_text('changed gate')
        with self.assertRaisesRegex(ValueError, 'boot file differs'):
            proof()
        gate.write_bytes(original)
        link = self.units / 'multi-user.target.wants' / bootstrap.UNITS[0]
        link.unlink()
        with self.assertRaisesRegex(ValueError, 'not enabled'):
            proof()
        link.symlink_to('../' + bootstrap.UNITS[0])
        recovery = self.root / 'usr/lib/elderbrain-recovery'
        selector = recovery / 'active.json'
        selector.chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'metadata must be private'):
            proof()
        selector.chmod(0o600)
        manifest = recovery / result['bundle'] / 'bundle.json'
        manifest.chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'manifest must be private'):
            proof()
        manifest.chmod(0o600)
        (recovery / result['bundle'] / 'release_baseline_install.py').write_text('damaged')
        with self.assertRaisesRegex(ValueError, 'bytes differ'):
            proof()

    def test_interrupted_publication_retains_history_and_unready_receipt(self):
        original = bootstrap.publish
        def interrupted(path, value, mode):
            if path == self.previous:
                raise OSError('injected write failure')
            return original(path, value, mode)
        with patch.object(bootstrap, 'publish', side_effect=interrupted):
            with self.assertRaisesRegex(OSError, 'injected write failure'):
                self.install()
        recovery = self.root / 'usr/lib/elderbrain-recovery'
        receipt = json.loads((recovery / 'installation.json').read_text())
        self.assertEqual(receipt['state'], 'installing')
        self.assertFalse(receipt['activationReady'])
        self.assertTrue((recovery / receipt['history'] / 'previous.json').exists())
        self.assertEqual(self.previous.read_text(), 'old storage unit\n')
        self.assertEqual(self.install()['state'], 'installed')

    def test_online_candidate_is_retained_without_selection_until_commit(self):
        baseline = self.install()
        selector = self.root / 'usr/lib/elderbrain-recovery/active.json'
        before = selector.read_bytes()
        recovery_source = self.tree / 'runtime/release_recovery.py'
        recovery_source.write_bytes(recovery_source.read_bytes() + b'\n# candidate generation\n')
        prepared = bootstrap.prepare_candidate(self.tree, self.fixture.paths,
            state=self.state, host_root=self.root)
        self.assertEqual(prepared['active'], baseline['bundle'])
        self.assertNotEqual(prepared['candidate'], baseline['bundle'])
        self.assertEqual(selector.read_bytes(), before)
        self.assertEqual(bootstrap.verify_active(baseline['bundle'], host_root=self.root),
                         {'bundle': baseline['bundle']})
        bootstrap.commit_candidate(prepared['candidate'], state=self.state, host_root=self.root)
        self.assertEqual(bootstrap.verify_active(prepared['candidate'], host_root=self.root),
                         {'bundle': prepared['candidate']})

    def test_online_candidate_cannot_replace_fixed_bootstrap_generation(self):
        baseline = self.install()
        selector = self.root / 'usr/lib/elderbrain-recovery/active.json'
        before = selector.read_bytes()
        launcher = self.tree / 'bootstrap/recovery-launcher.py'
        launcher.write_bytes(launcher.read_bytes() + b'\n# changed generation\n')
        with self.assertRaisesRegex(ValueError, 'changes fixed recovery bootstrap'):
            bootstrap.prepare_candidate(self.tree, self.fixture.paths, state=self.state, host_root=self.root)
        self.assertEqual(selector.read_bytes(), before)
        self.assertEqual(bootstrap.verify_active(baseline['bundle'], host_root=self.root),
                         {'bundle': baseline['bundle']})


if __name__ == '__main__':
    unittest.main()
