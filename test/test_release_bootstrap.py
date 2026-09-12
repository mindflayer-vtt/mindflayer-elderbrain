import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import test.test_release_prepare as preparation_fixture
from backup_service import Maintenance, save_record
import release_bootstrap as bootstrap
from release_staging import stage

spec = importlib.util.spec_from_file_location(
    'bootstrap_recovery_launcher', Path(__file__).resolve().parents[1] / 'provisioning/update/recovery-launcher.py')
launcher_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher_module)


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
        self.override = self.units / 'elderbrain-storage.service.d/user.conf'
        self.override.parent.mkdir()
        self.override.write_text('user-owned override\n')

    def install(self):
        return bootstrap.install(self.tree, self.fixture.paths, state=self.state, host_root=self.root)

    def test_install_publishes_one_generation_and_preserves_unrelated_override(self):
        result = self.install()
        self.assertEqual(result['state'], 'installed')
        self.assertFalse(result['activationReady'])
        recovery = self.root / 'usr/lib/elderbrain-recovery'
        self.assertEqual(bootstrap.active_generation(directory=recovery)['id'], result['generation'])
        self.assertEqual(self.override.read_text(), 'user-owned override\n')
        for target, source in bootstrap.files().items():
            self.assertTrue((self.root / target).is_symlink())
            self.assertEqual((self.root / target).read_bytes(), (self.tree / source).read_bytes())
        for name in bootstrap.UNITS:
            self.assertEqual((self.units / 'multi-user.target.wants' / name).readlink(), Path('../' + name))
        again = self.install()
        self.assertEqual(again, result)

    def test_unfinished_maintenance_keeps_boot_files_and_selector_unchanged(self):
        maintenance = self.state / 'maintenance'
        maintenance.mkdir(mode=0o700)
        save_record(maintenance / 'maintenance.json', {'state': 'working'})
        with self.assertRaisesRegex(RuntimeError, 'maintenance'):
            self.install()
        self.assertFalse(self.previous.exists())
        self.assertFalse((self.root / 'usr/lib/elderbrain-recovery/bootstrap-active').exists())

    def test_symlinked_target_and_conflicting_enablement_rejected_before_mutation(self):
        self.previous.symlink_to(self.override)
        with self.assertRaisesRegex(ValueError, 'Unsafe bootstrap generation anchor'):
            self.install()
        self.assertFalse((self.root / 'usr/lib/elderbrain-recovery/bootstrap-active').exists())
        self.previous.unlink()
        wants = self.units / 'multi-user.target.wants'
        wants.mkdir()
        (wants / bootstrap.UNITS[0]).symlink_to('../unrelated.service')
        with self.assertRaisesRegex(ValueError, 'Unexpected bootstrap enablement'):
            self.install()
        self.assertFalse((self.root / 'usr/lib/elderbrain-recovery/bootstrap-active').exists())

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

    def test_maintenance_remains_locked_through_generation_publication(self):
        original = bootstrap.publish_generation
        observed = []
        def checked(identity, *, directory):
            maintenance = Maintenance(self.state / 'maintenance', None)
            with self.assertRaisesRegex(RuntimeError, 'Another maintenance'):
                with maintenance.locked():
                    self.fail('Bootstrap released maintenance lock before publication')
            observed.append(identity)
            return original(identity, directory=directory)
        with patch.object(bootstrap, 'publish_generation', side_effect=checked):
            self.install()
        self.assertEqual(len(observed), 1)

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
        recovery = self.root / 'usr/lib/elderbrain-recovery'
        generation = recovery / bootstrap.GENERATIONS / result['generation']
        gate = generation / 'root/etc/systemd/system/docker.service.d/20-update-recovery.conf'
        gate.chmod(0o600)
        with self.assertRaisesRegex(ValueError, 'generation file differs'):
            proof()
        gate.chmod(0o644)
        link = self.units / 'multi-user.target.wants' / bootstrap.UNITS[0]
        link.unlink()
        with self.assertRaisesRegex(ValueError, 'not enabled'):
            proof()
        link.symlink_to('../' + bootstrap.UNITS[0])
        selector = generation / 'active.json'
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

    def test_interrupted_initial_publication_has_no_partial_active_generation(self):
        with patch.object(bootstrap, 'publish_generation', side_effect=OSError('injected write failure')):
            with self.assertRaisesRegex(OSError, 'injected write failure'):
                self.install()
        recovery = self.root / 'usr/lib/elderbrain-recovery'
        self.assertFalse((recovery / bootstrap.ACTIVE).exists())
        self.assertFalse((recovery / 'installation.json').exists())
        self.assertEqual(self.install()['state'], 'installed')

    def test_online_candidate_is_retained_without_selection_until_commit(self):
        baseline = self.install()
        recovery = self.root / 'usr/lib/elderbrain-recovery'
        selector = recovery / bootstrap.ACTIVE
        before = selector.readlink()
        recovery_source = self.tree / 'runtime/release_recovery.py'
        recovery_source.write_bytes(recovery_source.read_bytes() + b'\n# candidate generation\n')
        prepared = bootstrap.prepare_candidate(self.tree, self.fixture.paths, recovery_api=1,
            state=self.state, host_root=self.root)
        self.assertEqual(prepared['active'], baseline['bundle'])
        candidate = bootstrap.verify_generation(prepared['candidate'], directory=recovery)
        self.assertNotEqual(candidate['bundle'], baseline['bundle'])
        self.assertEqual(selector.readlink(), before)
        self.assertEqual(bootstrap.verify_active(baseline['bundle'], 1, host_root=self.root),
                         {'bundle': baseline['bundle'], 'recoveryApi': 1})
        bootstrap.commit_candidate(prepared['candidate'], state=self.state, host_root=self.root)
        self.assertEqual(bootstrap.verify_active(candidate['bundle'], 1, host_root=self.root),
                         {'bundle': candidate['bundle'], 'recoveryApi': 1})

    def test_installed_launcher_resolves_bundle_from_atomic_generation(self):
        baseline = self.install()
        recovery = self.root / 'usr/lib/elderbrain-recovery'
        self.assertEqual(launcher_module.selected(recovery),
                         recovery / baseline['bundle'] / 'release_recovery.py')

    def test_online_switch_reloads_live_systemd_manager(self):
        run = Mock()
        bootstrap.reload_units(Path('/'), run)
        run.assert_called_once()
        args, options = run.call_args
        self.assertEqual(args[0], ['/usr/bin/systemctl', 'daemon-reload'])
        self.assertTrue(options['check'])
        run.reset_mock()
        bootstrap.reload_units(self.root, run)
        run.assert_not_called()

    def test_candidate_switch_converges_before_and_after_atomic_commit_point(self):
        baseline = self.install()
        recovery = self.root / 'usr/lib/elderbrain-recovery'
        source = self.tree / 'bootstrap/writer-recovery.conf'
        source.write_bytes(source.read_bytes() + b'\n# candidate gate\n')
        prepared = bootstrap.prepare_candidate(self.tree, self.fixture.paths, recovery_api=1,
                                               state=self.state, host_root=self.root)
        candidate = bootstrap.verify_generation(prepared['candidate'], directory=recovery)
        with patch.object(bootstrap, 'publish_generation', side_effect=OSError('before selector')):
            with self.assertRaisesRegex(OSError, 'before selector'):
                bootstrap.commit_candidate(prepared['candidate'], state=self.state, host_root=self.root)
        self.assertEqual(bootstrap.active_generation(directory=recovery)['id'], baseline['generation'])
        original = os.replace
        def interrupted_after_replace(source_path, destination_path):
            original(source_path, destination_path)
            if Path(destination_path) == recovery / bootstrap.ACTIVE:
                raise OSError('after selector')
        with patch.object(bootstrap.os, 'replace', side_effect=interrupted_after_replace):
            with self.assertRaisesRegex(OSError, 'after selector'):
                bootstrap.commit_candidate(prepared['candidate'], state=self.state, host_root=self.root)
        self.assertEqual(bootstrap.active_generation(directory=recovery), candidate)
        self.assertIn(b'# candidate gate',
                      (self.units / 'docker.service.d/20-update-recovery.conf').read_bytes())
        self.assertEqual(bootstrap.commit_candidate(
            prepared['candidate'], state=self.state, host_root=self.root),
            {'bundle': candidate['bundle'], 'generation': candidate['id']})

    def test_interrupted_candidate_generation_publication_remains_unselected(self):
        baseline = self.install()
        recovery = self.root / 'usr/lib/elderbrain-recovery'
        generations = recovery / bootstrap.GENERATIONS
        source = self.tree / 'bootstrap/elderbrain-update-recovery.service'
        source.write_bytes(source.read_bytes() + b'\n# next generation\n')
        original = os.rename
        def fail_before(source_path, destination_path):
            if Path(destination_path).parent == generations:
                raise OSError('before generation rename')
            return original(source_path, destination_path)
        with patch.object(bootstrap.os, 'rename', side_effect=fail_before):
            with self.assertRaisesRegex(OSError, 'before generation rename'):
                bootstrap.prepare_candidate(self.tree, self.fixture.paths, recovery_api=1,
                                            state=self.state, host_root=self.root)
        self.assertEqual(bootstrap.active_generation(directory=recovery)['id'], baseline['generation'])
        self.assertEqual(len([path for path in generations.iterdir() if path.name[0] != '.']), 1)
        def fail_after(source_path, destination_path):
            original(source_path, destination_path)
            if Path(destination_path).parent == generations:
                raise OSError('after generation rename')
        with patch.object(bootstrap.os, 'rename', side_effect=fail_after):
            with self.assertRaisesRegex(OSError, 'after generation rename'):
                bootstrap.prepare_candidate(self.tree, self.fixture.paths, recovery_api=1,
                                            state=self.state, host_root=self.root)
        self.assertEqual(bootstrap.active_generation(directory=recovery)['id'], baseline['generation'])
        candidates = [path.name for path in generations.iterdir()
                      if path.name[0] != '.' and path.name != baseline['generation']]
        self.assertEqual(len(candidates), 1)
        bootstrap.verify_generation(candidates[0], directory=recovery)
        prepared = bootstrap.prepare_candidate(self.tree, self.fixture.paths, recovery_api=1,
                                               state=self.state, host_root=self.root)
        self.assertEqual(prepared['candidate'], candidates[0])

    def test_changed_fixed_bootstrap_is_staged_then_atomically_selected(self):
        baseline = self.install()
        recovery = self.root / 'usr/lib/elderbrain-recovery'
        selector = recovery / bootstrap.ACTIVE
        before = selector.readlink()
        launcher = self.tree / 'bootstrap/recovery-launcher.py'
        launcher.write_bytes(launcher.read_bytes() + b'\n# changed generation\n')
        prepared = bootstrap.prepare_candidate(self.tree, self.fixture.paths, recovery_api=1,
                                               state=self.state, host_root=self.root)
        self.assertEqual(selector.readlink(), before)
        self.assertNotEqual(bootstrap.verify_generation(prepared['candidate'], directory=recovery)['id'],
                            baseline['generation'])
        self.assertEqual(bootstrap.verify_active(baseline['bundle'], 1, host_root=self.root),
                         {'bundle': baseline['bundle'], 'recoveryApi': 1})
        bootstrap.commit_candidate(prepared['candidate'], state=self.state, host_root=self.root)
        self.assertIn(b'# changed generation',
                      (self.root / 'usr/libexec/elderbrain-recovery.py').read_bytes())

    def test_invalid_candidate_launcher_is_never_published(self):
        baseline = self.install()
        recovery = self.root / 'usr/lib/elderbrain-recovery'
        (self.tree / 'bootstrap/recovery-launcher.py').write_bytes(b'def broken(:\n')
        with self.assertRaisesRegex(ValueError, 'Invalid bootstrap launcher'):
            bootstrap.prepare_candidate(self.tree, self.fixture.paths, recovery_api=1,
                                        state=self.state, host_root=self.root)
        self.assertEqual(bootstrap.active_generation(directory=recovery)['id'], baseline['generation'])


if __name__ == '__main__':
    unittest.main()
